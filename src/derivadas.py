"""
Séries derivadas: séries NOVAS, calculadas a partir das coletadas, nunca da rede.

As regras vivem em `config/derivadas.yaml` e estão descritas em `content/metodologia.md`.
Aqui só se implementa. Três operações:

    residual         total − soma(componentes)
    soma             soma(componentes)
    media_ponderada  Σ(valor_i × peso_i) / Σ(peso_i)

Não confundir com `src/transformacoes.py`. Lá ficam as quatro BASES (R$ correntes,
R$ constantes, % do PIB, variação em 12 meses), que são jeitos diferentes de exibir uma
série que já existe. Aqui ficam séries que não existem em fonte nenhuma: a parcela
"Outros" que fecha a composição de um gráfico de saldo, o total de uma tabela do BCB que
não tem coluna de total publicada, e a inadimplência agregada por porte.

Determinismo. Em qualquer das três operações, uma data só entra no resultado quando
TODAS as séries envolvidas têm observação naquela data. Nada é interpolado, extrapolado,
repetido ou arredondado. Uma série derivada cujo insumo esteja ausente numa execução
simplesmente não é produzida — e o guard de regressão de `build_dataset.py` decide se
isso pode ser publicado.
"""

from __future__ import annotations

from comum import agora_iso

OPERACOES = ("residual", "soma", "media_ponderada")


class ErroDerivada(RuntimeError):
    """Falha determinística no cálculo de uma série derivada."""


# ---------------------------------------------------------------- operações


def _datas_comuns(*series: dict[str, float]) -> list[str]:
    """Datas em que todas as séries têm observação, em ordem cronológica."""
    if not series:
        return []
    comuns = set(series[0])
    for s in series[1:]:
        comuns &= set(s)
    return sorted(comuns)


def residual(total: list[list], componentes: list[list[list]]) -> list[list]:
    """
    `total − soma(componentes)`, nas datas em que todos existem.

    É o que garante que as parcelas exibidas num gráfico de saldo fechem exatamente no
    total publicado pela fonte. Só faz sentido sobre valores aditivos: aplicar a mesma
    ideia a taxas produziria um número sem significado, e por isso os gráficos de
    inadimplência usam a série "Outros" do próprio BCB.
    """
    t = dict(total)
    comps = [dict(c) for c in componentes]
    return [[d, t[d] - sum(c[d] for c in comps)] for d in _datas_comuns(t, *comps)]


def soma(componentes: list[list[list]]) -> list[list]:
    """`soma(componentes)`, nas datas em que todos existem."""
    comps = [dict(c) for c in componentes]
    return [[d, sum(c[d] for c in comps)] for d in _datas_comuns(*comps)]


def media_ponderada(pares: list[tuple[list[list], list[list]]]) -> list[list]:
    """
    `Σ(valor_i × peso_i) / Σ(peso_i)`, nas datas em que todos existem.

    Agrega taxas, que não somam. É como o próprio Banco Central constrói os seus totais
    de inadimplência: ponderando a taxa de cada recorte pelo saldo daquele recorte.
    Data em que a soma dos pesos é zero fica de fora — a divisão não existiria.
    """
    valores = [dict(v) for v, _ in pares]
    pesos = [dict(p) for _, p in pares]
    saida = []
    for d in _datas_comuns(*valores, *pesos):
        den = sum(p[d] for p in pesos)
        if den == 0:
            continue
        saida.append([d, sum(v[d] * p[d] for v, p in zip(valores, pesos)) / den])
    return saida


# ---------------------------------------------------------------- orquestração


def _insumos(serie: dict) -> list[str]:
    """Todo `serie_id` de que esta derivada depende, na ordem em que aparece no YAML."""
    op = serie["operacao"]
    if op == "residual":
        return [serie["total"]] + list(serie["componentes"])
    if op == "soma":
        return list(serie["componentes"])
    if op == "media_ponderada":
        return [x for par in serie["componentes"] for x in (par["serie"], par["peso"])]
    raise ErroDerivada(f"{serie['serie_id']}: operação desconhecida {op!r}")


def _calcula(serie: dict, obs_de: dict[str, list[list]]) -> list[list]:
    op = serie["operacao"]
    if op == "residual":
        return residual(obs_de[serie["total"]], [obs_de[c] for c in serie["componentes"]])
    if op == "soma":
        return soma([obs_de[c] for c in serie["componentes"]])
    return media_ponderada(
        [(obs_de[p["serie"]], obs_de[p["peso"]]) for p in serie["componentes"]]
    )


def _frase_calculo(serie: dict, codigos: dict[str, str]) -> str:
    """Fórmula explícita, com os códigos da fonte, para a página e a Metodologia."""
    op = serie["operacao"]
    if op == "residual":
        partes = " + ".join(codigos[c] for c in serie["componentes"])
        return f"calculada: código {codigos[serie['total']]} − ({partes})"
    if op == "soma":
        return "calculada: " + " + ".join(codigos[c] for c in serie["componentes"])
    termos = " + ".join(
        f"{codigos[p['serie']]}×{codigos[p['peso']]}" for p in serie["componentes"]
    )
    pesos = " + ".join(codigos[p["peso"]] for p in serie["componentes"])
    return f"calculada: ({termos}) ÷ ({pesos})"


def constroi(
    config: dict,
    payloads: dict[str, dict],
    catalogo: dict[str, dict],
) -> tuple[dict[str, dict], dict[str, dict]]:
    """
    Calcula todas as séries derivadas possíveis.

    Devolve (payloads derivados, entradas de catálogo). Insumo ausente naquela execução
    — fonte fora do ar e sem cache — apenas deixa a derivada de fora, do mesmo modo que
    a coleta faz com a série de origem.
    """
    derivados: dict[str, dict] = {}
    entradas: dict[str, dict] = {}

    for serie in config.get("series", []):
        serie_id = serie["serie_id"]
        insumos = _insumos(serie)

        faltando = [i for i in insumos if i not in payloads]
        if faltando:
            print(f"[PULA ] {serie_id:<38} sem insumo: {', '.join(faltando)}")
            continue

        obs_de = {i: payloads[i]["obs"] for i in insumos}
        obs = _calcula(serie, obs_de)
        if not obs:
            print(f"[PULA ] {serie_id:<38} sem data comum entre os insumos")
            continue

        codigos = {i: payloads[i]["codigo_fonte"] for i in insumos}
        derivados[serie_id] = {
            "serie_id": serie_id,
            "fonte": config.get("fonte", "Derivado"),
            "codigo_fonte": " / ".join(dict.fromkeys(codigos.values())),
            "unidade": serie["unidade"],
            "periodicidade": payloads[insumos[0]]["periodicidade"],
            "coletado_em": agora_iso(),
            "obs": obs,
        }
        entradas[serie_id] = {
            **serie,
            "codigo": " / ".join(dict.fromkeys(codigos.values())),
            "periodicidade": payloads[insumos[0]]["periodicidade"],
            "tabela": catalogo.get(insumos[0], {}).get("tabela", ""),
            "calculo": _frase_calculo(serie, codigos),
            "insumos": insumos,
        }

    return derivados, entradas


def confere_fechamento(
    config: dict, payloads: dict[str, dict], tolerancia: float = 1e-6
) -> list[str]:
    """
    Verifica que cada residual realmente fecha a composição.

    Recalcula `total − soma(componentes) − residual` e exige zero, a menos de erro de
    ponto flutuante. É a tradução em teste do item do checklist de aceite "cada gráfico
    de saldo fecha: soma das parcelas exibidas = Total, em todas as datas". Devolve a
    lista de problemas; vazia quer dizer que fechou.
    """
    problemas = []
    for serie in config.get("series", []):
        if serie["operacao"] != "residual":
            continue
        serie_id = serie["serie_id"]
        if serie_id not in payloads:
            continue
        total = dict(payloads[serie["total"]]["obs"])
        comps = [dict(payloads[c]["obs"]) for c in serie["componentes"]]
        resid = dict(payloads[serie_id]["obs"])
        for d, r in resid.items():
            sobra = total[d] - sum(c[d] for c in comps) - r
            if abs(sobra) > tolerancia * max(abs(total[d]), 1.0):
                problemas.append(f"{serie_id}: {d} não fecha por {sobra:.6f}")
    return problemas
