"""
Séries derivadas: séries NOVAS, calculadas a partir das coletadas, nunca da rede.

As regras vivem em `config/derivadas.yaml` e estão descritas em `content/metodologia.md`.
Aqui só se implementa. Três operações:

    residual         total − soma(componentes)
    soma             soma(componentes)
    media_ponderada  Σ(valor_i × peso_i) / Σ(peso_i)

Não confundir com `src/transformacoes.py`. Lá ficam as seis BASES (R$ correntes,
R$ constantes, acumulado em 12 meses, % do PIB, variação mensal e variação em 12 meses),
que são jeitos diferentes de exibir uma série que já existe. Aqui ficam séries que não existem em fonte nenhuma: a parcela
"Outros" que fecha a composição de um gráfico de saldo, o total de uma tabela do BCB que
não tem coluna de total publicada, e a inadimplência agregada por porte.

Determinismo. Em qualquer das três operações, uma data só entra no resultado quando
TODAS as séries envolvidas têm observação naquela data. Nada é interpolado, extrapolado,
repetido ou arredondado. Uma série derivada cujo insumo esteja ausente numa execução
simplesmente não é produzida — e o guard de regressão de `build_dataset.py` decide se
isso pode ser publicado.
"""

from __future__ import annotations

OPERACOES = ("residual", "soma", "media_ponderada")

# Quanto um residual pode ficar abaixo de zero sem reprovar, na unidade da fonte (todos
# os residuais de `config/derivadas.yaml` estão em R$ milhões). O SGS publica cada série
# arredondada em R$ 1 milhão, de forma independente: com um total e até seis parcelas, o
# arredondamento sozinho desloca o residual em no máximo 3,5. 5 cobre isso com folga e
# continua a milhares de vezes do menor residual observado — R$ 25.245 milhões
# (conc_livre_pf_outros, 05/2020, conferido no cache em 04/10/2026).
TOLERANCIA_RESIDUAL = 5.0


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
            # A coleta mais ANTIGA entre os insumos, e não a hora do cálculo: uma derivada
            # é tão recente quanto o seu insumo mais velho. Com um insumo vindo do cache,
            # carimbar "agora" faria a série calculada parecer mais nova do que o dado é.
            "coletado_em": min(payloads[i]["coletado_em"] for i in insumos),
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


def confere_residuais(
    config: dict, payloads: dict[str, dict], tolerancia: float = TOLERANCIA_RESIDUAL
) -> list[str]:
    """
    Exige que toda parcela residual seja maior ou igual a zero, a menos de `tolerancia`.

    SUBSTITUI a antiga `confere_fechamento`, que recalculava `total − soma − residual` e
    exigia zero: como o residual é DEFINIDO por essa conta, o teste não podia falhar, e
    não conferia nada. O que de fato denuncia um erro de catálogo é o sinal. Um residual
    negativo quer dizer que as parcelas exibidas somam mais que o total — parcela de outra
    tabela, código trocado, ou o total de cartão no lugar da parcela à vista (ver
    `config/derivadas.yaml`). Nesses casos o gráfico mostraria uma composição que não
    existe, e o build para.

    Devolve a lista de problemas, no máximo um por série (a data do pior caso).
    """
    problemas = []
    for serie in config.get("series", []):
        if serie["operacao"] != "residual":
            continue
        serie_id = serie["serie_id"]
        if serie_id not in payloads:
            continue
        pior_data, pior = min(
            ((d, v) for d, v in payloads[serie_id]["obs"]), key=lambda o: o[1]
        )
        if pior < -tolerancia:
            problemas.append(
                f"{serie_id}: residual negativo ({pior:,.1f}) em {pior_data} — as parcelas "
                f"exibidas somam mais que o total {serie['total']}"
            )
    return problemas
