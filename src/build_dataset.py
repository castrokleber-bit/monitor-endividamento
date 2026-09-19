"""
Coleta, normaliza, deriva, transforma e consolida todas as séries do catálogo.

Saídas:
  data/series.parquet   formato longo canônico (serie_id, data, valor, fonte, ...)
  data/series.json      o mesmo formato longo em JSON colunar
  data/manifest.json    procedência e frescor de cada série
  data/historico.json   o que mudou a cada execução, para a aba Metodologia
  data/estado.json      última coleta boa, mês-base do deflator, vintage do PIB
  docs/dados.js         payload embutido em `window.MONITOR`, lido pelo front

Por que `docs/dados.js` e não um `fetch()` de JSON: a página tem de abrir por `file://`
e servida no GitHub Pages com o mesmo código. Sob `file://` o navegador bloqueia
`fetch()` de arquivo local; um `<script src>` carrega nos dois casos.

ONDE AS TRANSFORMAÇÕES SÃO FEITAS. Aqui, em Python, e não no navegador. As quatro bases
do seletor (R$ correntes, R$ constantes, % do PIB, variação em 12 meses) são calculadas
no pipeline e viajam prontas no payload. Calcular no front economizaria tamanho de
arquivo, mas duplicaria a fórmula — uma cópia em Python para a planilha, outra em
JavaScript para o gráfico — e duas implementações da mesma regra divergem. O CLAUDE.md
é explícito: a camada de dados é determinística e o front não interpreta dado.

Política de falha. Uma série problemática nunca derruba o build das outras:

  - fonte caiu, há cache      -> `status: stale`, com `ultima_coleta_ok` no manifesto
  - fonte caiu, não há cache  -> `status: ausente`; a série fica fora dos artefatos
  - em ambos os casos os artefatos são escritos e o processo sai com 0

O que protege a publicação é o guard de regressão: se uma série que tinha dado na
execução anterior some, o processo escreve tudo mas sai com código 2, para o CI parar
antes do commit.

Códigos de saída: 0 ok | 1 configuração inconsistente | 2 regressão de cobertura.

Uso:
    python src/build_dataset.py
    python src/build_dataset.py --fonte bcb
    python src/build_dataset.py --sem-guard
    python src/build_dataset.py --do-cache   # reconstrói do cache, sem rede
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import build_metodologia
import derivadas
import fetch_bcb
import fetch_fred
import transformacoes
from comum import (
    COLUNAS,
    DATA,
    DOCS,
    PAUSA,
    agora_brasilia,
    agora_iso,
    carrega_abas,
    carrega_catalogo,
    carrega_env,
    carrega_metodologia,
    escreve_texto,
    grava_cache,
    grava_json,
    le_cache,
)

CATALOGOS = {"bcb": "series_bcb.yaml", "fred": "series_fred.yaml"}
CATALOGO_DERIVADAS = "derivadas.yaml"

# Tolerância do teste que confere a transformação "% do PIB" contra o % do PIB oficial
# do BCB, em pontos percentuais. A fonte publica com duas casas decimais, então metade
# da última casa (0,005 pp) é o máximo que arredondamento sozinho pode explicar. Medido
# em 19/09/2026 sobre seis pares de séries: a diferença máxima observada foi exatamente
# 0,005 pp. Qualquer coisa acima disso é diferença de vintage do PIB, e o build para.
TOLERANCIA_PIB_PP = 0.01


# ---------------------------------------------------------------- coleta


def coleta_serie(serie: dict, fonte: str, api_key: str | None) -> tuple[dict | None, dict]:
    """
    Coleta uma série. Em falha, cai para o cache anterior.

    Nunca levanta: uma série problemática não pode derrubar o build das outras.
    Devolve (payload, entrada_do_manifesto), com `status`:

      ok       coleta nova bem-sucedida
      stale    a fonte falhou e o cache anterior foi reutilizado
      ausente  a fonte falhou e não há cache — a série fica fora dos artefatos
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
        payload = fetch_bcb.coleta(serie) if fonte == "bcb" else fetch_fred.coleta(serie, api_key)
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


def do_cache(serie: dict, fonte: str) -> tuple[dict | None, dict]:
    """
    Reconstrói uma série a partir do cache, sem tocar na rede.

    Usado por `--do-cache`, que existe para iterar no front, no texto da Metodologia ou
    na planilha sem repetir a coleta inteira — são cento e oito requisições com pausa
    entre elas, e nenhuma delas muda quando o que mudou foi um arquivo em docs/.

    O status resultante é `ok`, não `stale`: o dado é o mesmo que a última coleta trouxe,
    e marcá-lo como desatualizado poria um aviso falso na página. O que a flag não faz é
    buscar dado novo — por isso ela é de uso manual e não aparece no CI.
    """
    serie_id = serie["serie_id"]
    base = {
        "serie_id": serie_id,
        "fonte": fetch_bcb.FONTE if fonte == "bcb" else fetch_fred.FONTE,
        "codigo_fonte": str(serie["codigo"]),
        "unidade": serie["unidade"],
        "periodicidade": serie.get("periodicidade", "M"),
    }
    payload = le_cache(serie_id)
    if payload is None:
        return None, {
            **base,
            "status": "ausente",
            "motivo": "sem cache local (--do-cache não vai à rede)",
            "ultima_coleta_ok": None,
            "n_obs": 0,
        }
    obs = payload["obs"]
    return payload, {
        **base,
        "status": "ok",
        "motivo": None,
        "ultima_coleta_ok": payload["coletado_em"],
        "coletado_em": payload["coletado_em"],
        "inicio": obs[0][0],
        "ultima_data": obs[-1][0],
        "ultimo_valor": obs[-1][1],
        "n_obs": len(obs),
    }


def coleta_tudo(
    fontes: list[str], apenas_cache: bool = False
) -> tuple[dict[str, dict], list[dict], dict[str, dict]]:
    """Percorre os catálogos e devolve (payloads, manifesto, metadados do catálogo)."""
    api_key = None
    if "fred" in fontes and not apenas_cache:
        try:
            api_key = fetch_fred.chave()
        except fetch_bcb.ErroColeta as exc:
            print(f"\n!! {exc}\n")

    payloads: dict[str, dict] = {}
    manifesto: list[dict] = []
    catalogo: dict[str, dict] = {}

    for fonte in fontes:
        cat = carrega_catalogo(CATALOGOS[fonte])
        print(f"\n=== {cat['fonte']} — {len(cat['series'])} série(s) ===\n")
        for serie in cat["series"]:
            catalogo[serie["serie_id"]] = serie
            if apenas_cache:
                payload, entrada = do_cache(serie, fonte)
            else:
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
            if not apenas_cache:
                time.sleep(PAUSA)

    return payloads, manifesto, catalogo


# ---------------------------------------------------------------- derivação


def deriva_tudo(
    payloads: dict[str, dict],
    catalogo: dict[str, dict],
    manifesto: list[dict],
) -> tuple[dict, dict[str, dict]]:
    """
    Calcula as séries derivadas e as insere nos payloads, no catálogo e no manifesto.

    Devolve (config de derivadas.yaml, entradas de catálogo das séries calculadas) —
    os dois são usados depois, na verificação de fechamento e na aba Metodologia.

    Muta os três, na ordem em que `main` os usa. Uma série derivada é indistinguível de
    uma coletada daqui para a frente — mesma estrutura, mesmo formato longo, mesma linha
    na planilha —, e o que a identifica como calculada é o campo `calculo`, exibido no
    lugar da procedência de fonte.
    """
    config = carrega_catalogo(CATALOGO_DERIVADAS)
    print(f"\n=== Derivadas — {len(config.get('series', []))} declarada(s) ===\n")
    novos, entradas = derivadas.constroi(config, payloads, catalogo)

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

    return config, entradas


# ---------------------------------------------------------------- transformação


def transforma_tudo(
    payloads: dict[str, dict],
    catalogo: dict[str, dict],
    ctx: transformacoes.Contexto,
) -> dict[str, dict]:
    """
    Aplica a cada série as bases que o catálogo dela declara.

    Devolve `{serie_id: {"datas": [...], "bases": {...}, "unidades": {...}, ...}}`.

    Todas as bases de uma série compartilham o mesmo eixo de datas, o da base nominal —
    as demais são sempre subconjuntos dela, porque só removem meses (sem IPCA, sem PIB,
    sem par de doze meses antes) e nunca acrescentam. Os meses removidos viram `null`,
    que é o buraco que o gráfico não liga e o CSV deixa em branco. Isso mantém o payload
    com um eixo de datas por série em vez de quatro.
    """
    saida: dict[str, dict] = {}

    for serie_id, payload in payloads.items():
        cfg = catalogo[serie_id]
        bases = list(cfg.get("bases") or [])
        fator = float(cfg.get("fator", 1))

        nominais = transformacoes.nominal(payload["obs"], fator)
        datas = [d for d, _ in nominais]
        posicao = {d: i for i, d in enumerate(datas)}

        valores: dict[str, list] = {"nominal": [v for _, v in nominais]}
        unidades: dict[str, str] = {"nominal": ctx.unidade("nominal", cfg)}
        calculos: dict[str, str | None] = {"nominal": None}

        for base in bases:
            if base == "nominal":
                continue
            if not ctx.disponivel(base):
                # Insumo da transformação não veio nesta execução. A base some do
                # seletor daquele gráfico; a série nominal continua lá.
                continue
            calculada = transformacoes.aplica(base, payload["obs"], cfg, ctx)
            coluna: list[float | None] = [None] * len(datas)
            for d, v in calculada:
                if d in posicao:
                    coluna[posicao[d]] = v
            valores[base] = coluna
            unidades[base] = ctx.unidade(base, cfg)
            calculos[base] = ctx.calculo(base, payload["codigo_fonte"])

        saida[serie_id] = {
            "datas": datas,
            "valores": valores,
            "unidades": unidades,
            "calculos": calculos,
            # `dict.fromkeys` preserva a ordem e tira a duplicata: `nominal` vem sempre
            # primeiro e o catálogo costuma declará-la de novo em `bases`.
            "bases": [b for b in dict.fromkeys(("nominal", *bases)) if b in valores],
        }

    return saida


# ---------------------------------------------------------------- consolidação


def para_formato_longo(payloads: dict[str, dict]) -> pd.DataFrame:
    """
    Converte os payloads no formato longo canônico definido em CLAUDE.md.

    O valor aqui é o da FONTE, na unidade original — sem `fator`, sem deflação, sem
    razão ao PIB. É o artefato de reprocessamento, e tem de ser o dado cru.
    """
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
    linhas do parquet. Reconstrói com `pandas.DataFrame(payload["dados"])`.

    Colunar e não um objeto por linha porque o arquivo é versionado e recommitado a cada
    atualização: sem repetir os sete nomes de coluna em cada observação, o artefato fica
    cerca de três vezes menor.
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


def inicio_do_grafico(ids: list[str], transformadas: dict[str, dict], regra) -> str | None:
    """
    Onde o intervalo "Tudo" de um gráfico começa. A regra vem de `config/abas.yaml`.

      comum          primeira data em que TODAS as séries do gráfico têm observação
      uniao          primeira observação de qualquer série do gráfico
      "AAAA-MM-DD"   data fixa

    O padrão `comum` existe por um caso concreto, documentado no YAML: o total do SFN
    (20539) tem observações desde 06/1988, mas todas as suas aberturas começam em
    03/2007, e os valores anteriores a 1994 estão reexpressos em reais a ponto de serem
    degenerados. Com `uniao`, dois gráficos abririam numa linha reta no zero por vinte
    anos. O recorte é só de exibição: data/, a planilha e o CSV do gráfico seguem com a
    série inteira desde a primeira observação da fonte.
    """
    inicios = [transformadas[i]["datas"][0] for i in ids if transformadas.get(i, {}).get("datas")]
    if not inicios:
        return None
    if regra == "comum":
        return max(inicios)
    if regra == "uniao":
        return min(inicios)
    return regra


def monta_payload(
    payloads: dict[str, dict],
    manifesto: list[dict],
    catalogo: dict[str, dict],
    transformadas: dict[str, dict],
    metodologia_blocos: list[dict],
) -> dict:
    """Monta o payload que a página consome: abas, gráficos, séries e procedência."""
    estados = {m["serie_id"]: m for m in manifesto}
    config = carrega_abas()
    inicio_padrao = config.get("inicio_padrao", "comum")
    # Ver a nota sobre dado preliminar no cabeçalho de config/series_bcb.yaml.
    prefixo_preliminar = carrega_catalogo(CATALOGOS["bcb"]).get("prefixo_tabela_preliminar")

    series = {}
    for serie_id, payload in payloads.items():
        cfg = catalogo[serie_id]
        entrada = estados[serie_id]
        t = transformadas[serie_id]
        series[serie_id] = {
            "rotulo": cfg.get("rotulo") or cfg.get("descricao_esperada") or serie_id,
            "descricao": cfg.get("descricao_esperada", ""),
            "fonte": payload["fonte"],
            "codigo_fonte": payload["codigo_fonte"],
            "tabela": cfg.get("tabela", ""),
            "periodicidade": payload["periodicidade"],
            "segmento": cfg.get("segmento"),
            # Papel de cor declarado no catálogo. O front resolve o token a partir dele,
            # nunca pela posição da série no gráfico — é o que mantém "PJ é sempre ocre"
            # em todos os gráficos em que PJ aparece.
            "cor": cfg.get("cor"),
            # A última observação desta série é preliminar na fonte?
            "preliminar": bool(
                prefixo_preliminar
                and str(cfg.get("tabela", "")).startswith(prefixo_preliminar)
            ),
            # `papel: total` engrossa o traço da curva no gráfico. Vem do catálogo e não
            # de heurística sobre o nome da série: "total" no slug não é garantia de
            # nada, e uma heurística erraria justamente nos gráficos em que o agregado
            # tem outro nome.
            "papel": cfg.get("papel"),
            # Só séries derivadas têm `calculo`: a página mostra a regra de cálculo no
            # lugar da linha de procedência de fonte.
            "calculo": cfg.get("calculo"),
            "status": entrada["status"],
            "inicio": entrada["inicio"],
            "ultima_data": entrada["ultima_data"],
            "n_obs": entrada["n_obs"],
            "datas": t["datas"],
            "valores": t["valores"],
            "unidades": t["unidades"],
            "calculos": t["calculos"],
            "bases": t["bases"],
        }

    abas = []
    for aba in config["abas"]:
        graficos = []
        for grafico in aba.get("graficos", []):
            presentes = [s for s in grafico["series"] if s in series]
            if not presentes:
                continue

            # A base só entra no seletor se TODAS as séries do gráfico a têm: misturar
            # bases dentro de um gráfico é proibido pela orientação, e um seletor que
            # oferece uma base que só metade das curvas sabe desenhar mente.
            bases = [
                b
                for b in (grafico.get("bases") or [])
                if all(b in series[s]["bases"] for s in presentes)
            ]
            detalhe = grafico.get("detalhe")
            if detalhe:
                por = [s for s in detalhe["por"] if s in series]
                detalhe = {**detalhe, "por": por} if por else None

            graficos.append(
                {
                    **grafico,
                    "series": presentes,
                    "bases": bases,
                    "base_padrao": grafico.get("base_padrao", bases[0] if bases else None),
                    "detalhe": detalhe,
                    "inicio": inicio_do_grafico(
                        presentes, transformadas, grafico.get("inicio", inicio_padrao)
                    ),
                }
            )
        abas.append(
            {
                "id": aba["id"],
                "titulo": aba["titulo"],
                "subtitulo": aba.get("subtitulo", ""),
                "nota_metodologica": aba.get("nota_metodologica"),
                "graficos": graficos,
            }
        )

    return {
        "gerado_em": agora_iso(),
        "atualizado_em": agora_brasilia(),
        "desatualizadas": [m["serie_id"] for m in manifesto if m["status"] == "stale"],
        "bases": config["bases"],
        "periodos": config["periodos"],
        "periodo_padrao": config.get("periodo_padrao", "tudo"),
        # Texto humano de content/, transportado sem alteração, e os blocos factuais
        # gerados do catálogo. O front encaixa um no outro pelos marcadores.
        "metodologia_texto": carrega_metodologia(),
        "metodologia_blocos": metodologia_blocos,
        "abas": abas,
        "series": series,
    }


# ---------------------------------------------------------------- verificações


# Arquivos do front cuja versão precisa andar junto com a do HTML que os carrega.
ESTATICOS = ("app.js", "style.css", "tokens.css")


def carimba_versao() -> str | None:
    """
    Carimba `?v=<hash>` nos estáticos referenciados por `docs/index.html`.

    O GitHub Pages serve tudo com `Cache-Control: max-age=600` e um `Age` independente
    por arquivo. Sem carimbo, um visitante que volte dentro dessa janela pode receber o
    HTML novo com o `app.js` antigo ainda em cache — e uma mudança de estrutura como a de
    19/09/2026, que trocou os ids do HTML, transforma essa combinação em PÁGINA EM BRANCO.
    Foi o que aconteceu ao conferir a publicação daquele dia.

    O carimbo é o hash do CONTEÚDO dos três arquivos, não a data da execução: assim ele
    só muda quando o front muda de fato, e a atualização quinzenal de dados não gera
    diff em `index.html`. A substituição é idempotente — reaplicar troca o carimbo
    existente em vez de acumular.
    """
    caminho = DOCS / "index.html"
    if not caminho.exists():
        return None

    digestor = hashlib.sha256()
    for nome in ESTATICOS:
        arquivo = DOCS / nome
        if arquivo.exists():
            digestor.update(arquivo.read_bytes())
    versao = digestor.hexdigest()[:10]

    html = caminho.read_text(encoding="utf-8")
    # Só dentro de `href=` e `src=`: sem isso o carimbo também entrava nas menções aos
    # arquivos escritas em prosa, dentro dos comentários do HTML.
    padrao = re.compile(
        r'(?P<attr>(?:href|src)=")(?P<arq>'
        + "|".join(re.escape(n) for n in ESTATICOS)
        + r')(?:\?v=[0-9a-f]+)?(?P<fim>")'
    )
    novo = padrao.sub(
        lambda m: f"{m.group('attr')}{m.group('arq')}?v={versao}{m.group('fim')}", html
    )
    if novo != html:
        escreve_texto(caminho, novo)
    return versao


def le_manifesto_anterior() -> list[dict]:
    """Manifesto da execução anterior, para o guard de regressão e para o histórico."""
    caminho = DATA / "manifest.json"
    if not caminho.exists():
        return []
    try:
        return json.loads(caminho.read_text(encoding="utf-8")).get("series", [])
    except ValueError:
        return []


def verifica_regressao(
    novo: list[dict], anterior: list[dict], no_catalogo: set[str] | None = None
) -> tuple[list[str], list[str]]:
    """
    Compara o manifesto novo com o da execução anterior.

    Devolve (bloqueios, avisos). Bloqueio é regressão de cobertura — série que tinha
    dado e deixou de ter. Perda de observações dentro de uma série que continua presente
    é apenas aviso: revisão da fonte pode legitimamente encurtar uma série.

    `no_catalogo` é o conjunto de `serie_id` que o catálogo declara AGORA. Série retirada
    ou renomeada de propósito no YAML sai do universo comparado: é decisão humana
    registrada em commit, não fonte que caiu. Sem esse filtro, qualquer renomeação de
    slug derrubaria o build inteiro na execução seguinte.
    """
    if not anterior:
        return [], []

    com_dado = {m["serie_id"] for m in novo if m["status"] in ("ok", "stale")}
    antes_com_dado = {m["serie_id"] for m in anterior if m["status"] in ("ok", "stale")}
    if no_catalogo is not None:
        antes_com_dado &= no_catalogo

    bloqueios = [
        f"{serie_id}: tinha dado na execução anterior e agora está ausente"
        for serie_id in sorted(antes_com_dado - com_dado)
    ]

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
    """Catálogo inteiro, independentemente das fontes coletadas nesta execução."""
    series: dict[str, dict] = {}
    for arquivo in list(CATALOGOS.values()) + [CATALOGO_DERIVADAS]:
        for serie in carrega_catalogo(arquivo)["series"]:
            series[serie["serie_id"]] = serie
    return series


def graficos_por_serie() -> dict[str, list[str]]:
    """Para cada série, os títulos dos gráficos em que ela aparece. Vai para a ficha."""
    mapa: dict[str, list[str]] = {}
    for aba in carrega_abas()["abas"]:
        for grafico in aba.get("graficos", []):
            ids = list(grafico["series"])
            detalhe = grafico.get("detalhe")
            if detalhe:
                ids += list(detalhe["por"])
            for serie_id in ids:
                mapa.setdefault(serie_id, []).append(grafico["titulo"])
    return mapa


def confere_referencias(catalogo: dict[str, dict]) -> list[str]:
    """Aponta séries citadas em abas.yaml que não existem no catálogo de séries."""
    faltantes = []
    for aba in carrega_abas()["abas"]:
        for grafico in aba.get("graficos", []):
            ids = list(grafico["series"])
            detalhe = grafico.get("detalhe")
            if detalhe:
                ids += list(detalhe["por"]) + [detalhe["substitui"]]
            for serie_id in ids:
                if serie_id not in catalogo:
                    faltantes.append(f"{aba['id']}/{grafico['id']}: {serie_id}")
    return faltantes


def confere_bases(catalogo: dict[str, dict]) -> list[str]:
    """
    Garante que toda base pedida por um gráfico seja declarada por todas as séries dele.

    Sem isto, um gráfico poderia oferecer "% do PIB" com metade das curvas vazias. A
    orientação é explícita: a transformação se aplica a todas as séries do gráfico ao
    mesmo tempo, nunca a algumas.
    """
    problemas = []
    for aba in carrega_abas()["abas"]:
        for grafico in aba.get("graficos", []):
            ids = list(grafico["series"])
            detalhe = grafico.get("detalhe")
            if detalhe:
                ids += list(detalhe["por"])
            for base in grafico.get("bases") or []:
                faltam = [
                    s for s in ids if base not in (catalogo.get(s, {}).get("bases") or [])
                ]
                if faltam:
                    problemas.append(
                        f"{aba['id']}/{grafico['id']}: base {base!r} pedida mas não "
                        f"declarada em {', '.join(faltam)}"
                    )
    return problemas


def confere_segmento(catalogo: dict[str, dict]) -> list[str]:
    """
    Garante que toda série citada em algum gráfico tenha `segmento` definido.

    O filtro por segmento saiu da página em 19/09/2026, mas o campo continua sendo
    metadado obrigatório: é o que a ficha de série da aba Metodologia mostra ao leitor
    para dizer a quem aquele número se refere.
    """
    problemas = []
    for aba in carrega_abas()["abas"]:
        for grafico in aba.get("graficos", []):
            ids = list(grafico["series"])
            detalhe = grafico.get("detalhe")
            if detalhe:
                ids += list(detalhe["por"])
            for serie_id in ids:
                segmento = catalogo.get(serie_id, {}).get("segmento")
                if segmento not in ("familia", "empresa", "ambos"):
                    problemas.append(
                        f"{aba['id']}/{grafico['id']}: {serie_id} tem "
                        f"segmento={segmento!r}, precisa ser familia, empresa ou ambos"
                    )
    return problemas


def confere_ancoras() -> list[str]:
    """
    Garante que toda âncora citada por um gráfico exista em `content/metodologia.md`.

    O campo `metodologia` de um gráfico é o alvo do ícone "i", e as âncoras são escritas
    à mão no markdown como `{#nome}`. Um `##` reescrito sem a âncora, ou um typo no YAML,
    deixaria o ícone levando a lugar nenhum — e isso não dá erro em JavaScript, só não
    acontece nada. Como toda a explicação do painel mudou de lugar para a aba Metodologia
    em 19/09/2026, um ícone quebrado é hoje um gráfico sem método ao alcance do leitor.
    """
    texto = carrega_metodologia()
    ancoras = set(re.findall(r"\{#([a-z0-9-]+)\}", texto))
    problemas = []
    for aba in carrega_abas()["abas"]:
        for grafico in aba.get("graficos", []):
            alvo = grafico.get("metodologia")
            if alvo and alvo not in ancoras:
                problemas.append(
                    f"{aba['id']}/{grafico['id']}: ícone \"i\" aponta para {alvo!r}, "
                    "que não existe em content/metodologia.md"
                )
    return problemas


def confere_marcadores() -> list[str]:
    """
    Garante que `content/metodologia.md` chame todos os blocos gerados.

    O front encaixa um bloco no fim da aba quando o texto esquece de chamá-lo, para que
    nada suma da página; esta verificação existe para que o esquecimento também seja
    visível a quem edita o arquivo, em vez de só reordenar a aba em silêncio.
    """
    texto = carrega_metodologia()
    chamados = set(re.findall(r"\{\{([a-z_]+)\}\}", texto))
    faltam = [m for m in build_metodologia.MARCADORES if m not in chamados]
    return [
        f"content/metodologia.md não chama {{{{{m}}}}} — o bloco vai para o fim da aba"
        for m in faltam
    ]


def confere_brasil_primeiro(catalogo: dict[str, dict]) -> list[str]:
    """
    Garante que a série do Brasil seja a primeira de todo gráfico que a contenha.

    A regra de identidade visual manda o Brasil na primeira cor da paleta. O front
    atribui cor pela ordem das séries, então a regra se cumpre pela ordenação em
    abas.yaml — e esta verificação existe para que ela não dependa de alguém lembrar.
    """
    problemas = []
    for aba in carrega_abas()["abas"]:
        for grafico in aba.get("graficos", []):
            paises = [catalogo.get(s, {}).get("pais") for s in grafico["series"]]
            if "BR" not in paises or paises[0] == "BR":
                continue
            posicao = paises.index("BR")
            problemas.append(
                f"{aba['id']}/{grafico['id']}: a série do Brasil "
                f"({grafico['series'][posicao]}) está na posição {posicao + 1} e "
                "precisa ser a primeira, para receber a primeira cor da paleta"
            )
    return problemas


def confere_pib_oficial(
    payloads: dict[str, dict], catalogo: dict[str, dict], ctx: transformacoes.Contexto
) -> list[str]:
    """
    Confere a transformação "% do PIB" contra o % do PIB que o próprio BCB publica.

    É o item do checklist de aceite "% do PIB calculado reproduz o % PIB oficial do BCB
    onde ele existe". As séries de referência estão no catálogo com `papel:
    referencia_pib` e `referencia_de` apontando para o saldo correspondente; elas não
    vão a gráfico nenhum, existem só para este teste.

    O % do PIB do painel continua vindo do cálculo próprio, não do oficial — é o que
    mantém todas as parcelas de um mesmo gráfico calculadas do mesmo jeito. O oficial é
    o padrão-ouro contra o qual o cálculo é conferido, como a orientação pede.
    """
    if not ctx.disponivel("pib"):
        return []
    problemas = []
    for serie_id, cfg in catalogo.items():
        if cfg.get("papel") != "referencia_pib":
            continue
        alvo = cfg.get("referencia_de")
        if serie_id not in payloads or alvo not in payloads:
            continue
        oficial = dict(payloads[serie_id]["obs"])
        calculado = dict(
            transformacoes.pib(payloads[alvo]["obs"], 1, ctx.pib_12m)
        )
        pior_data, pior = None, 0.0
        for d, v in calculado.items():
            if d not in oficial:
                continue
            dif = abs(v - oficial[d])
            if dif > pior:
                pior_data, pior = d, dif
        if pior > TOLERANCIA_PIB_PP:
            problemas.append(
                f"{alvo}: % do PIB calculado diverge do oficial ({serie_id}) em "
                f"{pior:.4f} pp em {pior_data} — provável diferença de vintage do PIB"
            )
    return problemas


# ---------------------------------------------------------------- main


def _falha(titulo: str, itens: list[str]) -> None:
    print(f"\nFALHA — {titulo}")
    for item in itens:
        print(f"  {item}")


def main() -> int:
    carrega_env()

    ap = argparse.ArgumentParser()
    ap.add_argument("--fonte", choices=["bcb", "fred", "todas"], default="todas")
    ap.add_argument(
        "--sem-guard",
        action="store_true",
        help="escreve os artefatos mesmo com regressão de cobertura (uso manual)",
    )
    ap.add_argument(
        "--do-cache",
        action="store_true",
        dest="do_cache",
        help="reconstrói os artefatos do cache local, sem ir à rede (uso manual)",
    )
    args = ap.parse_args()
    fontes = ["bcb", "fred"] if args.fonte == "todas" else [args.fonte]

    anterior = le_manifesto_anterior()  # lido antes de sobrescrever
    payloads, manifesto, catalogo = coleta_tudo(fontes, apenas_cache=args.do_cache)
    config_derivadas, entradas_derivadas = deriva_tudo(payloads, catalogo, manifesto)

    completo = catalogo_completo()
    for titulo, problemas in (
        ("abas.yaml cita série inexistente no catálogo:", confere_referencias(completo)),
        ("base pedida por um gráfico e não declarada pela série:", confere_bases(completo)),
        ("série em gráfico sem `segmento` no catálogo:", confere_segmento(completo)),
        ("identidade visual: Brasil não está na primeira posição.", confere_brasil_primeiro(completo)),
        ('ícone "i" apontando para âncora inexistente:', confere_ancoras()),
    ):
        if problemas:
            _falha(titulo, problemas)
            return 1

    # Aviso, não falha: o bloco não some da página, só muda de lugar.
    for aviso in confere_marcadores():
        print(f"  aviso: {aviso}")

    nao_fecha = derivadas.confere_fechamento(config_derivadas, payloads)
    if nao_fecha:
        _falha("parcela residual não fecha no total publicado:", nao_fecha[:20])
        return 1

    ctx = transformacoes.Contexto(payloads, catalogo)
    divergencias = confere_pib_oficial(payloads, catalogo, ctx)
    if divergencias:
        _falha("% do PIB calculado não reproduz o oficial do BCB:", divergencias)
        return 1

    transformadas = transforma_tudo(payloads, catalogo, ctx)

    # ------------------------------------------------------------- Metodologia
    historico = build_metodologia.registra_historico(manifesto, anterior)
    pib_ultima = None
    for serie_id, cfg in catalogo.items():
        if cfg.get("papel") == "denominador_pib" and serie_id in payloads:
            pib_ultima = payloads[serie_id]["obs"][-1][0]

    blocos = [
        build_metodologia.bloco_fontes(manifesto, catalogo, agora_brasilia()),
        build_metodologia.bloco_transformacoes(carrega_abas()["bases"], ctx, pib_ultima),
        build_metodologia.bloco_derivadas(config_derivadas, entradas_derivadas),
        build_metodologia.bloco_ficha(manifesto, catalogo, graficos_por_serie()),
        build_metodologia.bloco_historico(historico),
    ]

    # ------------------------------------------------------------- artefatos
    df = para_formato_longo(payloads)
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DATA / "series.parquet", index=False)

    payload = monta_payload(payloads, manifesto, catalogo, transformadas, blocos)
    grava_json(DATA / "series.json", formato_longo_json(df, payload["gerado_em"]))
    grava_json(DATA / "manifest.json", {"gerado_em": payload["gerado_em"], "series": manifesto})
    build_metodologia.grava_historico(historico)

    # Arquivo de estado pedido na seção 7 da orientação. A página mostra a data da
    # última atualização a partir daqui, não da data de build.
    grava_json(
        DATA / "estado.json",
        {
            "ultima_coleta_ok": agora_iso(),
            "atualizado_em": agora_brasilia(),
            "proxima_coleta": build_metodologia.proxima_coleta(),
            "base_deflator": ctx.data_base,
            "vintage_pib": pib_ultima,
            "n_series": len(payloads),
            "ultima_observacao_por_serie": {
                m["serie_id"]: m.get("ultima_data") for m in manifesto
            },
        },
    )

    escreve_texto(
        DOCS / "dados.js",
        "// Gerado por src/build_dataset.py — não editar à mão.\n"
        "// Payload embutido para que a página funcione por file:// e no GitHub Pages.\n"
        "window.MONITOR = " + json.dumps(payload, ensure_ascii=False) + ";\n",
    )

    versao = carimba_versao()
    if versao:
        print(f"Estáticos do front carimbados com ?v={versao}")

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
    print(
        "Escrito: data/series.parquet, data/series.json, data/manifest.json, "
        "data/historico.json, data/estado.json, docs/dados.js"
    )

    bloqueios, avisos = verifica_regressao(manifesto, anterior, set(completo))
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
