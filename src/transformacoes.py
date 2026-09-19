"""
As cinco bases do seletor "Base de valores".

Este módulo é o único lugar do projeto onde um valor divulgado pela fonte vira outro
número. Todas as regras estão escritas em `content/metodologia.md` e declaradas em
`config/abas.yaml`; aqui só se implementa.

    nominal   valor da fonte multiplicado pelo `fator` de exibição do catálogo
    real      nominal deflacionado pelo IPCA, a preços do mês-base móvel
    pib       saldo dividido pelo PIB acumulado em 12 meses, em porcentagem
    var1m     variação percentual contra o mês anterior
    var12m    variação percentual contra o mesmo mês do ano anterior

Três garantias, em todas elas:

  - mês sem o insumo necessário (IPCA, PIB, ou o valor de doze meses antes) não entra no
    resultado. Nada é interpolado, extrapolado ou repetido;
  - nenhum arredondamento. O valor que sai daqui tem a precisão do float que entrou; quem
    arredonda é a formatação do front, e só na exibição;
  - a transformação é sempre calculada sobre o valor NOMINAL da fonte. `var12m` sobre a
    série real, por exemplo, não existe — seria inflação embutida duas vezes.

A conversão de unidade (`fator`) é parte da base `nominal` e se propaga às demais.
O SGS publica os saldos de crédito em R$ milhões e a página exibe em R$ bilhões, então
`fator: 0.001` no catálogo. O valor gravado no formato canônico (data/series.parquet,
data/series.json e as abas temáticas da planilha) continua na unidade original da fonte:
a conversão é de exibição, como manda o CLAUDE.md.
"""

from __future__ import annotations

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

# Marcador que abas.yaml e o front usam para receber o mês-base do deflator.
MARCADOR_BASE = "{base_ipca}"

BASES = ("nominal", "real", "pib", "var1m", "var12m")


class ErroTransformacao(RuntimeError):
    """Insumo faltando ou inconsistente para aplicar uma transformação."""


# ---------------------------------------------------------------- utilidades


def rotulo_mes(data_iso: str) -> str:
    """`2026-08-01` -> `ago/2026`. Usado no rótulo do eixo das séries a preços constantes."""
    ano, mes, _ = data_iso.split("-")
    return f"{MESES[int(mes) - 1]}/{ano}"


def doze_meses_antes(data_iso: str) -> str:
    """
    `2026-07-01` -> `2025-07-01`.

    Subtração de calendário, não de posição na lista: uma série com mês faltando não pode
    comparar com o décimo segundo ponto anterior, que seria outro mês. Todas as séries do
    catálogo referem o primeiro dia do período, então o dia é preservado como está.
    """
    ano, mes, dia = data_iso.split("-")
    return f"{int(ano) - 1:04d}-{mes}-{dia}"


def mes_anterior(data_iso: str) -> str:
    """
    `2026-07-01` -> `2026-06-01`; `2026-01-01` -> `2025-12-01`.

    Mesma razão de `doze_meses_antes` para ser subtração de calendário e não de posição:
    série com mês faltando compararia com o mês errado, e a variação sairia errada sem
    que nada avisasse.
    """
    ano, mes, dia = data_iso.split("-")
    ano, mes = int(ano), int(mes)
    return f"{ano - 1:04d}-12-{dia}" if mes == 1 else f"{ano:04d}-{mes - 1:02d}-{dia}"


def indice_ipca(obs_variacao: list[list]) -> dict[str, float]:
    """
    Índice de preços encadeado a partir da variação mensal do IPCA (SGS 433).

        I(t) = I(t-1) x (1 + variacao(t)/100)

    O nível do índice não tem significado próprio — só as razões entre dois meses são
    usadas, e por isso a base do encadeamento é irrelevante. O SGS não publica um
    número-índice do IPCA utilizável: o código 1737 devolve HTML com status 200, que é
    exatamente a armadilha registrada no CLAUDE.md.
    """
    if not obs_variacao:
        raise ErroTransformacao("deflator sem observações")
    indice: dict[str, float] = {}
    acumulado = 1.0
    for data_iso, variacao in obs_variacao:
        acumulado *= 1.0 + variacao / 100.0
        indice[data_iso] = acumulado
    return indice


def aplica_marcador(texto: str | None, data_base: str | None) -> str | None:
    """Troca `{base_ipca}` pelo mês-base nas unidades declaradas em config/."""
    if not texto or MARCADOR_BASE not in texto:
        return texto
    if data_base is None:
        # Sem deflator não há base; a unidade não pode inventar um mês que não existe.
        return texto.replace(MARCADOR_BASE, "mês-base indisponível")
    return texto.replace(MARCADOR_BASE, rotulo_mes(data_base))


# ---------------------------------------------------------------- as quatro bases


def _divisor_exato(fator: float) -> int | None:
    """
    Se `fator` é 1/n para um inteiro n, devolve n. Caso contrário, None.

    Existe por causa de um detalhe de ponto flutuante com consequência visível. O fator
    de R$ milhões para R$ bilhões é 0,001, que não tem representação exata em binário:
    `10284943 * 0.001` dá 10284.943000000001, e esse rastro de dezessete dígitos ia parar
    no CSV de download e na planilha. Dividir por 1000 dá 10284.943, o double mais
    próximo do valor certo.

    Não é arredondamento — nada é truncado nem perdido. É escolher, entre duas operações
    matematicamente idênticas, a que não introduz erro de representação.
    """
    if fator <= 0 or fator >= 1:
        return None
    inverso = 1.0 / fator
    arredondado = round(inverso)
    return arredondado if abs(inverso - arredondado) < 1e-9 else None


def nominal(obs: list[list], fator: float) -> list[list]:
    """Valor da fonte na unidade de exibição. `fator: 1` deixa a série intacta."""
    if fator == 1:
        return [[d, v] for d, v in obs]
    divisor = _divisor_exato(fator)
    if divisor is not None:
        return [[d, v / divisor] for d, v in obs]
    return [[d, v * fator] for d, v in obs]


def real(obs: list[list], fator: float, indice: dict[str, float], data_base: str) -> list[list]:
    """
    Valor a preços do mês `data_base`:  `nominal(t) x I(base) / I(t)`.

    Mês do saldo sem IPCA correspondente fica de fora — o deflator não cobre aquele mês
    e preenchê-lo exigiria estimativa. Por construção, o valor real do mês-base é igual
    ao nominal do mês-base, que é o que `tests/test_transformacoes.py` verifica.
    """
    if data_base not in indice:
        raise ErroTransformacao(f"mês-base {data_base} fora do deflator")
    nivel_base = indice[data_base]
    # `nominal` primeiro, para que a conversão de unidade use a divisão exata quando
    # puder — ver `_divisor_exato`.
    return [[d, v * nivel_base / indice[d]] for d, v in nominal(obs, fator) if d in indice]


def pib(obs: list[list], fator: float, pib_12m: dict[str, float]) -> list[list]:
    """
    Saldo em % do PIB acumulado em 12 meses:  `valor(t) / PIB12m(t) x 100`.

    O `fator` de exibição se cancela na razão, mas só quando numerador e denominador
    estão na mesma unidade original — e estão: o SGS publica os dois em R$ milhões. Por
    isso a razão é calculada nos valores ORIGINAIS, sem fator nenhum, e o resultado sai
    em porcentagem. Aplicar o fator aqui daria o mesmo número, e é justamente por isso
    que ele não é aplicado: um dia o fator do PIB pode mudar sem que o do saldo mude.

    Mês do saldo sem PIB correspondente fica de fora. Conferido em 19/09/2026: esta
    conta reproduz o % do PIB oficial do BCB com diferença máxima de 0,005 pp, que é o
    arredondamento de duas casas da própria fonte.
    """
    del fator  # documentado acima: a razão se faz nos valores originais
    return [[d, v / pib_12m[d] * 100.0] for d, v in obs if d in pib_12m and pib_12m[d]]


def _variacao(obs: list[list], anterior_de) -> list[list]:
    """
    Núcleo comum de `var1m` e `var12m`:  `(v(t)/v(anterior) - 1) x 100`.

    Calculada sobre o valor nominal, e por isso independente do `fator` de exibição —
    uma razão entre dois valores da mesma série cancela qualquer multiplicador.

    Observação cujo par anterior não existe, ou é zero, fica de fora, sem preenchimento.
    """
    valores = dict(obs)
    saida = []
    for d, v in obs:
        anterior = valores.get(anterior_de(d))
        if anterior is None or anterior == 0:
            continue
        saida.append([d, (v / anterior - 1.0) * 100.0])
    return saida


def var1m(obs: list[list]) -> list[list]:
    """
    Variação percentual contra o mês anterior:  `(v(t)/v(t-1) - 1) x 100`.

    A primeira observação de cada série fica de fora, sem preenchimento.

    Diferença de leitura em relação à variação em 12 meses, que a Metodologia registra:
    esta série NÃO é dessazonalizada, e os saldos de crédito têm sazonalidade marcada —
    dezembro e janeiro se comportam de modo distinto do resto do ano. O pipeline não
    aplica nem remove ajuste sazonal em série nenhuma.
    """
    return _variacao(obs, mes_anterior)


def var12m(obs: list[list]) -> list[list]:
    """
    Variação percentual contra o mesmo mês do ano anterior:  `(v(t)/v(t-12) - 1) x 100`.

    Calculada sobre o valor nominal, e por isso independente do `fator` de exibição —
    uma razão entre dois valores da mesma série cancela qualquer multiplicador.

    Os doze primeiros meses da série ficam de fora, sem preenchimento, e o mesmo vale
    para qualquer mês cujo par de doze meses antes não exista ou seja zero. A comparação
    é por data de calendário, não por posição: série com buraco não compara mês errado.
    """
    return _variacao(obs, doze_meses_antes)


# ---------------------------------------------------------------- orquestração


class Contexto:
    """
    Os insumos comuns a todas as transformações, montados uma vez por execução.

    `data_base` é o mês mais recente do IPCA — base móvel: a cada atualização os valores
    reais passam a estar a preços do último mês divulgado, e a unidade da série diz qual
    é esse mês.
    """

    def __init__(self, payloads: dict[str, dict], catalogo: dict[str, dict]) -> None:
        self.indice: dict[str, float] | None = None
        self.data_base: str | None = None
        self.pib_12m: dict[str, float] | None = None
        self.codigo_deflator: str | None = None
        self.codigo_pib: str | None = None

        for serie_id, cfg in catalogo.items():
            payload = payloads.get(serie_id)
            if payload is None:
                continue
            if cfg.get("papel") == "deflator":
                self.indice = indice_ipca(payload["obs"])
                self.data_base = payload["obs"][-1][0]
                self.codigo_deflator = payload["codigo_fonte"]
            elif cfg.get("papel") == "denominador_pib":
                self.pib_12m = dict(payload["obs"])
                self.codigo_pib = payload["codigo_fonte"]

    def disponivel(self, base: str) -> bool:
        """Diz se o insumo daquela base foi coletado nesta execução."""
        if base == "real":
            return self.indice is not None and self.data_base is not None
        if base == "pib":
            return self.pib_12m is not None
        return True

    def unidade(self, base: str, cfg: dict) -> str:
        """Unidade do eixo para cada base. `real` carrega o mês-base no próprio rótulo."""
        exibicao = cfg.get("unidade_exibicao") or cfg.get("unidade", "")
        if base == "nominal":
            return exibicao
        if base == "real":
            return f"{exibicao} de {rotulo_mes(self.data_base)}" if self.data_base else exibicao
        if base == "pib":
            return "% do PIB"
        if base == "var1m":
            return "% no mês"
        return "% em 12 meses"

    def calculo(self, base: str, codigo: str) -> str | None:
        """
        Frase de procedência que a página e a Metodologia exibem por série transformada.

        Existe para que ninguém tome um valor calculado aqui por valor divulgado pelo
        Banco Central.
        """
        if base == "nominal":
            return None
        if base == "real":
            return (
                f"código {codigo} (valores nominais) deflacionado pelo IPCA, código "
                f"{self.codigo_deflator}, a preços de {rotulo_mes(self.data_base)}"
            )
        if base == "pib":
            return (
                f"código {codigo} dividido pelo PIB acumulado em 12 meses, código "
                f"{self.codigo_pib}, em porcentagem"
            )
        if base == "var1m":
            return (
                f"variação percentual do código {codigo} contra o mês anterior, "
                "sem ajuste sazonal"
            )
        return f"variação percentual do código {codigo} contra o mesmo mês do ano anterior"


def aplica(base: str, obs: list[list], cfg: dict, ctx: Contexto) -> list[list]:
    """Aplica uma das cinco bases a uma série. Levanta se a base não existe."""
    fator = float(cfg.get("fator", 1))
    if base == "nominal":
        return nominal(obs, fator)
    if base == "real":
        if not ctx.disponivel("real"):
            raise ErroTransformacao("deflator indisponível nesta execução")
        return real(obs, fator, ctx.indice, ctx.data_base)
    if base == "pib":
        if not ctx.disponivel("pib"):
            raise ErroTransformacao("série do PIB indisponível nesta execução")
        return pib(obs, fator, ctx.pib_12m)
    if base == "var1m":
        return var1m(obs)
    if base == "var12m":
        return var12m(obs)
    raise ErroTransformacao(f"base desconhecida: {base}")
