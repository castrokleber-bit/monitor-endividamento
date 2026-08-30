"""
Coleta, normaliza e consolida todas as séries do catálogo.

Saídas:
  data/series.parquet   formato longo canônico (serie_id, data, valor, fonte, ...)
  data/series.json      o mesmo formato longo em JSON colunar (uma lista por coluna)
  data/manifest.json    procedência e frescor de cada série
  docs/dados.js         payload embutido em `window.MONITOR`, lido pelo front

Por que `docs/dados.js` e não um `fetch()` de JSON: a página tem de abrir por `file://`
e servida no GitHub Pages com o mesmo código. Sob `file://` o navegador bloqueia
`fetch()` de arquivo local; um `<script src>` carrega nos dois casos.

Política de falha. Uma série problemática nunca derruba o build das outras:

  - fonte caiu, há cache      -> `status: stale`, com `ultima_coleta_ok` no manifesto
  - fonte caiu, não há cache  -> `status: ausente`; a série fica fora dos artefatos
  - em ambos os casos os artefatos são escritos e o processo sai com 0

O que protege a publicação é o guard de regressão: se uma série que tinha dado na
execução anterior some, o processo escreve tudo mas sai com código 2, para o CI parar
antes do commit. É a leitura operacional do princípio 4 do CLAUDE.md — o dia ruim não
publica cobertura menor, mas também não impede a atualização das séries saudáveis.

Códigos de saída: 0 ok | 1 configuração inconsistente | 2 regressão de cobertura.

Uso:
    python src/build_dataset.py
    python src/build_dataset.py --fonte bcb
    python src/build_dataset.py --sem-guard
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import derivadas
import fetch_bcb
import fetch_fred
from comum import (
    COLUNAS,
    DATA,
    DOCS,
    PAUSA,
    agora_brasilia,
    agora_iso,
    carrega_blocos,
    carrega_catalogo,
    carrega_env,
    carrega_metodologia,
    grava_cache,
    grava_json,
    le_cache,
)

CATALOGOS = {"bcb": "series_bcb.yaml", "fred": "series_fred.yaml"}

# Catálogo das séries calculadas a partir das coletadas. Não vai à rede.
CATALOGO_DERIVADAS = "derivadas.yaml"


# ---------------------------------------------------------------- coleta


def coleta_serie(serie: dict, fonte: str, api_key: str | None) -> tuple[dict | None, dict]:
    """
    Coleta uma série. Em falha, cai para o cache anterior.

    Nunca levanta: uma série problemática não pode derrubar o build das outras.
    Devolve (payload, entrada_do_manifesto), com `status`:

      ok       coleta nova bem-sucedida
      stale    a fonte falhou e o cache anterior foi reutilizado
      ausente  a fonte falhou e não há cache — a série fica fora dos artefatos

    `ultima_coleta_ok` é sempre a data da última coleta que deu certo: em `stale`
    vem do cache, e é ela que diz há quanto tempo o dado exibido não é atualizado.
    """
    serie_id = serie["serie_id"]
    base = {
        "serie_id": serie_id,
        "fonte": fetch_bcb.FONTE if fonte == "bcb" else fetch_fred.FONTE,
        "codigo_fonte": str(serie["codigo"]),
        "unidade": serie["unidade"],
        "periodicidade": serie.get("periodicidade", "M"),
    }

    try:
        payload = (
            fetch_bcb.coleta(serie) if fonte == "bcb" else fetch_fred.coleta(serie, api_key)
        )
        grava_cache(serie_id, payload)
        estado, motivo = "ok", None
    except (fetch_bcb.ErroColeta, RuntimeError, ValueError, KeyError) as exc:
        payload = le_cache(serie_id)
        if payload is None:
            return None, {
                **base,
                "status": "ausente",
                "motivo": str(exc),
                "ultima_coleta_ok": None,
                "n_obs": 0,
            }
        estado, motivo = "stale", str(exc)

    obs = payload["obs"]
    return payload, {
        **base,
        "status": estado,
        "motivo": motivo,
        "ultima_coleta_ok": payload["coletado_em"],
        "coletado_em": payload["coletado_em"],
        "inicio": obs[0][0],
        "ultima_data": obs[-1][0],
        "ultimo_valor": obs[-1][1],
        "n_obs": len(obs),
    }


def coleta_tudo(fontes: list[str]) -> tuple[dict[str, dict], list[dict], dict[str, dict]]:
    """Percorre os catálogos e devolve (payloads, manifesto, metadados do catálogo)."""
    api_key = None
    if "fred" in fontes:
        try:
            api_key = fetch_fred.chave()
        except fetch_bcb.ErroColeta as exc:
            # Sem chave, cada série do FRED cai para o cache individualmente. Não é
            # motivo para derrubar a coleta do BCB.
            print(f"\n!! {exc}\n")

    payloads: dict[str, dict] = {}
    manifesto: list[dict] = []
    catalogo: dict[str, dict] = {}

    for fonte in fontes:
        cat = carrega_catalogo(CATALOGOS[fonte])
        print(f"\n=== {cat['fonte']} — {len(cat['series'])} série(s) ===\n")
        for serie in cat["series"]:
            catalogo[serie["serie_id"]] = serie
            payload, entrada = coleta_serie(serie, fonte, api_key)
            manifesto.append(entrada)
            if payload is not None:
                payloads[serie["serie_id"]] = payload
            marca = {"ok": "OK   ", "stale": "CACHE", "ausente": "SEM  "}[entrada["status"]]
            detalhe = (
                f"{entrada['n_obs']:>5} obs  até {entrada.get('ultima_data')}"
                if payload
                else entrada["motivo"]
            )
            print(f"[{marca}] {serie['serie_id']:<38} {detalhe}")
            if entrada["status"] == "stale":
                print(f"         !! usando cache anterior — {entrada['motivo']}")
            time.sleep(PAUSA)

    return payloads, manifesto, catalogo


# ---------------------------------------------------------------- derivação


def deriva_tudo(
    payloads: dict[str, dict],
    catalogo: dict[str, dict],
    manifesto: list[dict],
) -> str | None:
    """
    Calcula as séries derivadas e as insere nos payloads, no catálogo e no manifesto.

    Muta os três, na ordem em que `main` os usa. Devolve o mês-base do deflator, que a
    unidade dos gráficos precisa. Uma série derivada é indistinguível de uma coletada
    daqui para a frente — mesma estrutura, mesmo formato longo, mesma linha na planilha —,
    e o que a identifica como calculada é o campo `calculo` do catálogo, exibido no lugar
    da procedência de fonte na página.
    """
    config = carrega_catalogo(CATALOGO_DERIVADAS)
    novos, entradas, data_base = derivadas.constroi(config, payloads, catalogo)
    if not novos:
        return data_base

    print(f"\n=== Derivadas — {len(novos)} série(s) ===\n")
    for serie_id, payload in novos.items():
        obs = payload["obs"]
        payloads[serie_id] = payload
        catalogo[serie_id] = entradas[serie_id]
        manifesto.append(
            {
                "serie_id": serie_id,
                "fonte": payload["fonte"],
                "codigo_fonte": payload["codigo_fonte"],
                "unidade": payload["unidade"],
                "periodicidade": payload["periodicidade"],
                "status": "ok",
                "motivo": None,
                "ultima_coleta_ok": payload["coletado_em"],
                "coletado_em": payload["coletado_em"],
                "inicio": obs[0][0],
                "ultima_data": obs[-1][0],
                "ultimo_valor": obs[-1][1],
                "n_obs": len(obs),
            }
        )
        print(f"[CALC ] {serie_id:<38} {len(obs):>5} obs  até {obs[-1][0]}")

    return data_base


# ---------------------------------------------------------------- consolidação


def para_formato_longo(payloads: dict[str, dict]) -> pd.DataFrame:
    """Converte os payloads no formato longo canônico definido em CLAUDE.md."""
    linhas = []
    for payload in payloads.values():
        for data_iso, valor in payload["obs"]:
            linhas.append(
                {
                    "serie_id": payload["serie_id"],
                    "data": data_iso,
                    "valor": valor,
                    "fonte": payload["fonte"],
                    "codigo_fonte": payload["codigo_fonte"],
                    "unidade": payload["unidade"],
                    "periodicidade": payload["periodicidade"],
                }
            )
    df = pd.DataFrame(linhas, columns=COLUNAS)
    df["data"] = pd.to_datetime(df["data"])
    return df.sort_values(["serie_id", "data"]).reset_index(drop=True)


def formato_longo_json(df: pd.DataFrame, gerado_em: str) -> dict:
    """
    `data/series.json`: o formato longo canônico em disposição colunar.

    `dados` traz uma lista por coluna, todas do mesmo comprimento e na mesma ordem de
    linhas do parquet — a linha i é a i-ésima posição de cada lista. Reconstrói com
    `pandas.DataFrame(payload["dados"])`.

    Colunar e não um objeto por linha porque o arquivo é versionado e recommitado a cada
    atualização: sem repetir os sete nomes de coluna em cada uma das milhares de
    observações, o artefato fica cerca de três vezes menor e o histórico do repositório
    cresce na mesma proporção.

    Espelho legível do parquet, para quem for reprocessar sem pyarrow. O payload que a
    página consome é outro arquivo, `docs/dados.js`.
    """
    saida = df.copy()
    saida["data"] = saida["data"].dt.strftime("%Y-%m-%d")
    return {
        "gerado_em": gerado_em,
        "formato": "colunar",
        "colunas": COLUNAS,
        "n_observacoes": len(saida),
        "dados": {coluna: saida[coluna].tolist() for coluna in COLUNAS},
    }


def monta_payload(
    payloads: dict[str, dict],
    manifesto: list[dict],
    catalogo: dict[str, dict],
    base_deflator: str | None = None,
) -> dict:
    """Monta o payload que a página consome: blocos, gráficos, séries e procedência."""
    estados = {m["serie_id"]: m for m in manifesto}
    config = carrega_blocos()
    blocos_cfg = config["blocos"]

    series = {}
    for serie_id, payload in payloads.items():
        cfg = catalogo[serie_id]
        entrada = estados[serie_id]
        series[serie_id] = {
            "rotulo": cfg.get("rotulo") or cfg.get("descricao_esperada") or serie_id,
            "descricao": cfg.get("descricao_esperada", ""),
            "fonte": payload["fonte"],
            "codigo_fonte": payload["codigo_fonte"],
            "unidade": payload["unidade"],
            "periodicidade": payload["periodicidade"],
            "nota": cfg.get("nota"),
            # Só séries derivadas têm `calculo`: a página mostra a regra de cálculo no
            # lugar da linha de procedência de fonte.
            "calculo": cfg.get("calculo"),
            "status": entrada["status"],
            "coletado_em": entrada["coletado_em"],
            "inicio": entrada["inicio"],
            "ultima_data": entrada["ultima_data"],
            "n_obs": entrada["n_obs"],
            "obs": payload["obs"],
        }

    blocos = []
    for bloco in blocos_cfg:
        graficos = []
        for grafico in bloco.get("graficos", []):
            presentes = [s for s in grafico["series"] if s in series]
            if not presentes:
                continue
            graficos.append(
                {
                    **grafico,
                    "series": presentes,
                    # A unidade dos gráficos a preços constantes carrega o mês-base, que
                    # só se conhece depois de coletado o deflator.
                    "unidade": derivadas.aplica_marcador(grafico["unidade"], base_deflator),
                }
            )
        blocos.append(
            {
                "id": bloco["id"],
                "titulo": bloco["titulo"],
                "subtitulo": bloco.get("subtitulo", ""),
                "nota_metodologica": bloco.get("nota_metodologica"),
                "graficos": graficos,
            }
        )

    desatualizadas = [m["serie_id"] for m in manifesto if m["status"] == "stale"]
    return {
        "gerado_em": agora_iso(),
        # Mesma geração, já formatada no horário de Brasília: é o que a página mostra.
        "atualizado_em": agora_brasilia(),
        "desatualizadas": desatualizadas,
        # Recorte de exibição. As séries abaixo vão inteiras; quem corta é o front.
        "recorte": config.get("recorte", {}),
        # Texto humano de content/, transportado sem alteração.
        "metodologia": carrega_metodologia(),
        "blocos": blocos,
        "series": series,
    }


def le_manifesto_anterior() -> list[dict]:
    """Manifesto da execução anterior, para o guard de regressão. Vazio na primeira vez."""
    caminho = DATA / "manifest.json"
    if not caminho.exists():
        return []
    try:
        return json.loads(caminho.read_text(encoding="utf-8")).get("series", [])
    except ValueError:
        return []


def verifica_regressao(novo: list[dict], anterior: list[dict]) -> tuple[list[str], list[str]]:
    """
    Compara o manifesto novo com o da execução anterior.

    Devolve (bloqueios, avisos). Bloqueio é regressão de cobertura — série que tinha
    dado e deixou de ter, ou o total de séries com dado caindo. Isso não pode ser
    commitado em silêncio: o painel perderia uma série sem ninguém notar.

    Perda de observações dentro de uma série que continua presente é apenas aviso:
    revisão da fonte pode legitimamente encurtar uma série.
    """
    if not anterior:
        return [], []

    com_dado = {m["serie_id"] for m in novo if m["status"] in ("ok", "stale")}
    antes_com_dado = {m["serie_id"] for m in anterior if m["status"] in ("ok", "stale")}

    bloqueios = []
    for serie_id in sorted(antes_com_dado - com_dado):
        bloqueios.append(f"{serie_id}: tinha dado na execução anterior e agora está ausente")
    if len(com_dado) < len(antes_com_dado):
        bloqueios.append(
            f"cobertura caiu de {len(antes_com_dado)} para {len(com_dado)} série(s) com dado"
        )

    obs_antes = {m["serie_id"]: m.get("n_obs", 0) for m in anterior}
    avisos = []
    for m in novo:
        anterior_n = obs_antes.get(m["serie_id"])
        if anterior_n and m.get("n_obs", 0) < anterior_n:
            avisos.append(
                f"{m['serie_id']}: {anterior_n} -> {m['n_obs']} observações "
                "(revisão da fonte ou coleta incompleta)"
            )
    return bloqueios, avisos


def catalogo_completo() -> dict[str, dict]:
    """
    Catálogo inteiro, independentemente das fontes coletadas nesta execução.

    As verificações de configuração precisam disto: rodar `--fonte bcb` não torna as
    séries do FRED citadas em blocos.yaml inexistentes.
    """
    series: dict[str, dict] = {}
    for arquivo in list(CATALOGOS.values()) + [CATALOGO_DERIVADAS]:
        for serie in carrega_catalogo(arquivo)["series"]:
            series[serie["serie_id"]] = serie
    return series


def confere_referencias(catalogo: dict[str, dict]) -> list[str]:
    """Aponta séries citadas em blocos.yaml que não existem no catálogo de séries."""
    faltantes = []
    for bloco in carrega_blocos()["blocos"]:
        for grafico in bloco.get("graficos", []):
            for serie_id in grafico["series"]:
                if serie_id not in catalogo:
                    faltantes.append(f"{bloco['id']}/{grafico['titulo']}: {serie_id}")
    return faltantes


def confere_brasil_primeiro(catalogo: dict[str, dict]) -> list[str]:
    """
    Garante que a série do Brasil seja a primeira de todo gráfico que a contenha.

    A regra de identidade visual manda o Brasil na primeira cor da paleta (`--serie-1`,
    o azul institucional). O front atribui cor pela ordem das séries no gráfico, então a
    regra se cumpre pela ordenação em blocos.yaml. Esta verificação existe para que ela
    não dependa de alguém lembrar: quem inverter a ordem quebra o build, não a página.
    """
    problemas = []
    for bloco in carrega_blocos()["blocos"]:
        for grafico in bloco.get("graficos", []):
            paises = [catalogo.get(s, {}).get("pais") for s in grafico["series"]]
            if "BR" not in paises or paises[0] == "BR":
                continue
            posicao = paises.index("BR")
            problemas.append(
                f"{bloco['id']}/{grafico['titulo']}: a série do Brasil "
                f"({grafico['series'][posicao]}) está na posição {posicao + 1} e "
                "precisa ser a primeira, para receber a primeira cor da paleta"
            )
    return problemas


# ---------------------------------------------------------------- main


def main() -> int:
    carrega_env()

    ap = argparse.ArgumentParser()
    ap.add_argument("--fonte", choices=["bcb", "fred", "todas"], default="todas")
    ap.add_argument(
        "--sem-guard",
        action="store_true",
        help="escreve os artefatos mesmo com regressão de cobertura (uso manual)",
    )
    args = ap.parse_args()
    fontes = ["bcb", "fred"] if args.fonte == "todas" else [args.fonte]

    anterior = le_manifesto_anterior()  # lido antes de sobrescrever
    payloads, manifesto, catalogo = coleta_tudo(fontes)
    base_deflator = deriva_tudo(payloads, catalogo, manifesto)

    completo = catalogo_completo()

    faltantes = confere_referencias(completo)
    if faltantes:
        print("\nFALHA — blocos.yaml cita série inexistente no catálogo:")
        for f in faltantes:
            print(f"  {f}")
        return 1

    fora_de_ordem = confere_brasil_primeiro(completo)
    if fora_de_ordem:
        print("\nFALHA — identidade visual: Brasil não está na primeira posição.")
        for p in fora_de_ordem:
            print(f"  {p}")
        return 1

    # Os artefatos são sempre escritos: uma série problemática não impede a atualização
    # das demais. O que uma regressão faz é sinalizar no código de saída, para o CI
    # não commitar em silêncio.
    df = para_formato_longo(payloads)
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DATA / "series.parquet", index=False)

    payload = monta_payload(payloads, manifesto, catalogo, base_deflator)
    grava_json(DATA / "series.json", formato_longo_json(df, payload["gerado_em"]))
    grava_json(
        DATA / "manifest.json",
        {"gerado_em": payload["gerado_em"], "series": manifesto},
    )

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "dados.js").write_text(
        "// Gerado por src/build_dataset.py — não editar à mão.\n"
        "// Payload embutido para que a página funcione por file:// e no GitHub Pages.\n"
        "window.MONITOR = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    stale = [m for m in manifesto if m["status"] == "stale"]
    ausentes = [m for m in manifesto if m["status"] == "ausente"]

    print(
        f"\n{len(payloads)} série(s), {len(df):,} observações. "
        f"{len(stale)} desatualizada(s), {len(ausentes)} ausente(s)."
    )
    for m in stale:
        print(f"  stale   {m['serie_id']:<38} último dado bom em {m['ultima_coleta_ok']}")
    for m in ausentes:
        print(f"  ausente {m['serie_id']:<38} {m['motivo']}")
    print("Escrito: data/series.parquet, data/series.json, data/manifest.json, docs/dados.js")

    bloqueios, avisos = verifica_regressao(manifesto, anterior)
    for aviso in avisos:
        print(f"  aviso: {aviso}")
    if bloqueios:
        print("\nREGRESSÃO DE COBERTURA — os artefatos foram escritos, mas NÃO devem subir:")
        for b in bloqueios:
            print(f"  {b}")
        if args.sem_guard:
            print("--sem-guard: seguindo assim mesmo.")
            return 0
        print("Rode de novo quando a fonte voltar, ou use --sem-guard se a perda for esperada.")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
