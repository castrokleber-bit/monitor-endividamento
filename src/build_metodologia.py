"""
Monta a aba Metodologia a partir do catálogo, não à mão.

O princípio, vindo da orientação de 18/09/2026: o gráfico carrega só título, unidade,
legenda e um ícone "i"; toda a explicação vive numa aba própria. Para que essa aba não
desatualize, as partes factuais dela são GERADAS do catálogo a cada build:

    fontes       procedência, frequência de coleta, data da coleta e a próxima prevista
    ficha        uma linha por série: código, nome na fonte, tabela de origem, unidade
                 original, unidade exibida, conversão, cobertura, gráficos em que aparece
    derivadas    a fórmula explícita de cada residual, soma e média ponderada
    transformacoes  as quatro bases, o mês-base vigente do deflator e o vintage do PIB
    historico    o que mudou em relação à execução anterior

O texto humano — o que o monitor é, os conceitos, as limitações — continua em
`content/metodologia.md` e é transportado sem alteração, como manda o CLAUDE.md. Os
blocos gerados entram onde o arquivo humano colocar os marcadores `{{fontes}}`,
`{{ficha}}`, `{{derivadas}}`, `{{transformacoes}}` e `{{historico}}`.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from comum import BRASILIA, DATA, agora_iso, escreve_texto
from transformacoes import rotulo_mes

# Dias do mês em que o pipeline roda (ver .github/workflows/atualiza.yml).
DIAS_DE_COLETA = (1, 16)

MARCADORES = ("fontes", "ficha", "derivadas", "transformacoes", "historico")


# ---------------------------------------------------------------- calendário


def proxima_coleta(referencia: date | None = None) -> str:
    """Próximo dia 1 ou 16 a partir de hoje, em ISO. É o que a página anuncia."""
    hoje = referencia or datetime.now(BRASILIA).date()
    for dia in DIAS_DE_COLETA:
        if hoje.day < dia:
            return hoje.replace(day=dia).isoformat()
    proximo_mes = (hoje.replace(day=28) + timedelta(days=7)).replace(day=DIAS_DE_COLETA[0])
    return proximo_mes.isoformat()


# ---------------------------------------------------------------- blocos gerados


def bloco_fontes(manifesto: list[dict], catalogo: dict[str, dict], atualizado_em: str) -> dict:
    """Uma linha por fonte, com contagem de séries e a observação mais recente."""
    por_fonte: dict[str, dict] = {}
    for entrada in manifesto:
        fonte = entrada["fonte"]
        alvo = por_fonte.setdefault(fonte, {"fonte": fonte, "n_series": 0, "ultima_obs": ""})
        alvo["n_series"] += 1
        ultima = entrada.get("ultima_data") or ""
        if ultima > alvo["ultima_obs"]:
            alvo["ultima_obs"] = ultima

    del catalogo  # a procedência por série vai na ficha, não aqui
    return {
        "tipo": "fontes",
        "titulo": "Fontes",
        "atualizado_em": atualizado_em,
        "proxima_coleta": proxima_coleta(),
        "frequencia": "Quinzenal — dias 1 e 16 de cada mês, ao fim da tarde de Brasília.",
        "linhas": sorted(por_fonte.values(), key=lambda x: x["fonte"]),
    }


def bloco_ficha(
    manifesto: list[dict],
    catalogo: dict[str, dict],
    graficos_por_serie: dict[str, list[str]],
) -> dict:
    """
    A ficha de cada série. É o item 4 da estrutura pedida na orientação.

    `conversao` diz em uma frase o que foi feito com a unidade — nunca há conversão sem
    essa linha, que é a exigência do CLAUDE.md de registrar toda mudança de unidade.
    """
    linhas = []
    for entrada in sorted(manifesto, key=lambda m: m["serie_id"]):
        cfg = catalogo.get(entrada["serie_id"], {})
        fator = float(cfg.get("fator", 1))
        origem = cfg.get("unidade", entrada["unidade"])
        exibicao = cfg.get("unidade_exibicao") or origem
        linhas.append(
            {
                "serie_id": entrada["serie_id"],
                "nome_oficial": cfg.get("descricao_esperada", ""),
                "fonte": entrada["fonte"],
                "codigo": entrada["codigo_fonte"],
                "tabela": cfg.get("tabela", ""),
                "unidade_origem": origem,
                "unidade_exibicao": exibicao,
                "conversao": (
                    "nenhuma" if fator == 1 else f"valor da fonte × {fator:g} ({origem} → {exibicao})"
                ),
                "periodicidade": entrada["periodicidade"],
                "primeira_obs": entrada.get("inicio"),
                "ultima_obs": entrada.get("ultima_data"),
                "n_obs": entrada.get("n_obs", 0),
                "status": entrada.get("status"),
                "segmento": cfg.get("segmento", ""),
                "graficos": graficos_por_serie.get(entrada["serie_id"], []),
                "calculo": cfg.get("calculo"),
            }
        )
    return {"tipo": "ficha", "titulo": "Ficha por série", "linhas": linhas}


def bloco_derivadas(config_derivadas: dict, entradas: dict[str, dict]) -> dict:
    """A fórmula de cada série calculada, com os códigos da fonte que entram nela."""
    linhas = []
    for serie in config_derivadas.get("series", []):
        serie_id = serie["serie_id"]
        entrada = entradas.get(serie_id)
        if entrada is None:
            continue
        linhas.append(
            {
                "serie_id": serie_id,
                "rotulo": serie.get("rotulo", serie_id),
                "operacao": serie["operacao"],
                "formula": entrada.get("calculo", ""),
                "insumos": entrada.get("insumos", []),
                "unidade": serie.get("unidade_exibicao") or serie.get("unidade", ""),
                "descricao": serie.get("descricao_esperada", ""),
            }
        )
    return {"tipo": "derivadas", "titulo": "Séries derivadas", "linhas": linhas}


def bloco_transformacoes(bases: list[dict], ctx, pib_ultima: str | None) -> dict:
    """
    As quatro bases, com o mês-base vigente do deflator e o vintage do PIB.

    Os dois são móveis: mudam a cada atualização. Escrever isso à mão na Metodologia
    daria um texto errado na semana seguinte, que é exatamente o motivo de a aba ser
    gerada.
    """
    return {
        "tipo": "transformacoes",
        "titulo": "Transformações",
        "base_deflator": rotulo_mes(ctx.data_base) if ctx.data_base else None,
        "codigo_deflator": ctx.codigo_deflator,
        "codigo_pib": ctx.codigo_pib,
        "vintage_pib": rotulo_mes(pib_ultima) if pib_ultima else None,
        "linhas": [
            {"id": b["id"], "rotulo": b["rotulo"], "sufixo": b["sufixo"], "regra": b["descricao"]}
            for b in bases
        ],
    }


# ---------------------------------------------------------------- histórico


def _caminho_historico():
    return DATA / "historico.json"


def le_historico() -> list[dict]:
    caminho = _caminho_historico()
    if not caminho.exists():
        return []
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except ValueError:
        return []


def diferenca(novo: list[dict], anterior: list[dict]) -> dict:
    """
    O que mudou entre duas execuções: séries novas, séries que avançaram, revisões.

    "Revisão" aqui é o caso em que a última observação não avançou mas o número de
    observações mudou — sinal de que a fonte reescreveu o histórico, que é o
    comportamento normal do BCB e precisa ficar registrado.
    """
    antes = {m["serie_id"]: m for m in anterior}
    novas, avancaram, revisadas, sumiram = [], [], [], []

    for m in novo:
        velho = antes.get(m["serie_id"])
        if velho is None:
            novas.append(m["serie_id"])
            continue
        if (m.get("ultima_data") or "") > (velho.get("ultima_data") or ""):
            avancaram.append(
                {
                    "serie_id": m["serie_id"],
                    "de": velho.get("ultima_data"),
                    "para": m.get("ultima_data"),
                }
            )
        elif m.get("n_obs") != velho.get("n_obs"):
            revisadas.append(
                {
                    "serie_id": m["serie_id"],
                    "de": velho.get("n_obs"),
                    "para": m.get("n_obs"),
                }
            )

    agora = {m["serie_id"] for m in novo}
    sumiram = sorted(set(antes) - agora)

    return {
        "novas": sorted(novas),
        "avancaram": sorted(avancaram, key=lambda x: x["serie_id"]),
        "revisadas": sorted(revisadas, key=lambda x: x["serie_id"]),
        "sumiram": sumiram,
    }


def registra_historico(manifesto: list[dict], anterior: list[dict], limite: int = 40) -> list[dict]:
    """
    Acrescenta uma entrada ao histórico e devolve a lista inteira, da mais recente.

    Execução que não mudou nada não vira entrada — o pipeline roda a cada quinze dias e
    nem sempre há divulgação nova; um histórico cheio de "nada mudou" esconderia o que
    importa. `limite` evita que o arquivo cresça sem fim no repositório.
    """
    historico = le_historico()
    mudou = diferenca(manifesto, anterior)
    if not any(mudou.values()):
        return historico

    entrada = {
        "em": agora_iso(),
        "data": datetime.now(BRASILIA).date().isoformat(),
        "n_series": len(manifesto),
        **mudou,
    }
    historico = [entrada] + historico
    return historico[:limite]


def grava_historico(historico: list[dict]) -> None:
    escreve_texto(_caminho_historico(), json.dumps(historico, ensure_ascii=False, indent=1))


def bloco_historico(historico: list[dict]) -> dict:
    return {
        "tipo": "historico",
        "titulo": "Histórico de atualizações",
        "linhas": historico,
    }
