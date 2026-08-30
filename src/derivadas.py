"""
Séries derivadas: calculadas a partir das séries coletadas, nunca da rede.

Hoje há uma única operação, `deflaciona_ipca`, declarada em `config/derivadas.yaml`.
A regra está escrita lá e em `content/metodologia.md`; aqui só se implementa.

O índice de preços é encadeado a partir da variação mensal do IPCA (SGS 433):

    I(t) = I(t-1) x (1 + variacao(t)/100)

A base do índice é irrelevante — o que entra no cálculo é sempre uma razão I(base)/I(t).
O valor real é `nominal(t) x I(base) / I(t)`, com a base no mês mais recente do IPCA.

Determinismo: mês do saldo sem IPCA correspondente fica de fora da série derivada.
Nada é extrapolado, interpolado ou arredondado.
"""

from __future__ import annotations

from comum import agora_iso

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

# Marcador que `blocos.yaml` usa na unidade do gráfico para receber o mês da base.
MARCADOR_BASE = "{base_ipca}"


class ErroDerivada(RuntimeError):
    """Falha determinística no cálculo de uma série derivada."""


def rotulo_mes(data_iso: str) -> str:
    """`2026-07-01` -> `jul/2026`. Usado na unidade das séries a preços constantes."""
    ano, mes, _ = data_iso.split("-")
    return f"{MESES[int(mes) - 1]}/{ano}"


def indice_encadeado(obs_variacao: list[list]) -> dict[str, float]:
    """
    Índice de preços encadeado a partir de observações de variação percentual mensal.

    Devolve {data_iso: nível do índice}, com o primeiro mês já acumulado. O nível não
    tem significado próprio: só as razões entre dois meses são usadas.
    """
    if not obs_variacao:
        raise ErroDerivada("deflator sem observações")
    indice: dict[str, float] = {}
    acumulado = 1.0
    for data_iso, variacao in obs_variacao:
        acumulado *= 1.0 + variacao / 100.0
        indice[data_iso] = acumulado
    return indice


def deflaciona(obs_nominal: list[list], indice: dict[str, float], data_base: str) -> list[list]:
    """
    Converte observações nominais em valores a preços do mês `data_base`.

    Observação cuja data não existe no índice é omitida — o deflator não cobre aquele
    mês e preencher exigiria estimativa.
    """
    if data_base not in indice:
        raise ErroDerivada(f"mês-base {data_base} fora do deflator")
    nivel_base = indice[data_base]
    return [
        [data_iso, valor * nivel_base / indice[data_iso]]
        for data_iso, valor in obs_nominal
        if data_iso in indice
    ]


def _unidade_real(unidade_nominal: str, data_base: str) -> str:
    """`R$ milhões` -> `R$ milhões de jul/2026`."""
    return f"{unidade_nominal} de {rotulo_mes(data_base)}"


def constroi(
    config: dict,
    payloads: dict[str, dict],
    catalogo: dict[str, dict],
) -> tuple[dict[str, dict], dict[str, dict], str | None]:
    """
    Calcula todas as séries derivadas possíveis.

    Devolve (payloads derivados, entradas de catálogo, mês-base do IPCA). Uma origem
    ausente naquela execução — fonte fora do ar e sem cache — apenas deixa a série
    derivada de fora, do mesmo modo que a coleta faz com a série de origem: o guard de
    regressão de `build_dataset.py` é quem decide se isso pode ser publicado.
    """
    regra = config.get("deflacionamento") or {}
    deflator_id = regra.get("deflator")
    if not deflator_id or deflator_id not in payloads:
        return {}, {}, None

    indice = indice_encadeado(payloads[deflator_id]["obs"])
    data_base = payloads[deflator_id]["obs"][-1][0]

    derivados: dict[str, dict] = {}
    entradas: dict[str, dict] = {}

    for serie in config.get("series", []):
        origem_id = serie["origem"]
        if serie["operacao"] != "deflaciona_ipca":
            raise ErroDerivada(f"{serie['serie_id']}: operação desconhecida {serie['operacao']}")
        origem = payloads.get(origem_id)
        if origem is None:
            continue

        obs = deflaciona(origem["obs"], indice, data_base)
        if not obs:
            continue

        unidade = _unidade_real(origem["unidade"], data_base)
        codigo_origem = origem["codigo_fonte"]
        codigo_deflator = payloads[deflator_id]["codigo_fonte"]

        derivados[serie["serie_id"]] = {
            "serie_id": serie["serie_id"],
            "fonte": origem["fonte"],
            "codigo_fonte": f"{codigo_origem} / {codigo_deflator}",
            "unidade": unidade,
            "periodicidade": origem["periodicidade"],
            "coletado_em": agora_iso(),
            "obs": obs,
        }
        entradas[serie["serie_id"]] = {
            **serie,
            "unidade": unidade,
            "periodicidade": origem["periodicidade"],
            "codigo": f"{codigo_origem} / {codigo_deflator}",
            # Frase que a página exibe no lugar da procedência de série coletada.
            "calculo": (
                f"calculada: código {codigo_origem} (valores nominais) deflacionado pelo "
                f"IPCA, código {codigo_deflator}, a preços de {rotulo_mes(data_base)}"
            ),
        }

    return derivados, entradas, data_base


def aplica_marcador(texto: str | None, data_base: str | None) -> str | None:
    """Troca `{base_ipca}` pelo mês-base nas unidades declaradas em blocos.yaml."""
    if not texto or MARCADOR_BASE not in texto:
        return texto
    if data_base is None:
        # Sem deflator não há base; a unidade não pode mentir sobre um mês que não existe.
        return texto.replace(MARCADOR_BASE, "mês-base indisponível")
    return texto.replace(MARCADOR_BASE, rotulo_mes(data_base))
