"""
Coleta das séries do BCB / SGS.

Armadilhas tratadas aqui (ver CLAUDE.md):
  - o SGS recusa intervalos maiores que 10 anos em séries diárias -> paginação por janelas;
  - data vem como `dd/MM/yyyy` em string;
  - valor vem em string, com separador decimal ora ponto, ora vírgula;
  - `406` = código inexistente; `429` = rajada -> retry com backoff em `comum.http_get`;
  - a API pode devolver HTML de erro com status 200 -> o payload é validado antes do parse;
  - há série que RECUSA a consulta sem intervalo -> queda automática para janelas de data.

Sobre a última. Descoberta em 19/09/2026 na série 27703 (inadimplência de micro, pequenas
e médias empresas): a consulta sem `dataInicial`/`dataFinal` devolve `{"erro":{}}` com
status HTTP 200, e `/dados/ultimos/N` responde 400 para N maior que 20. A mesma série
entrega os 175 meses normalmente quando a consulta traz um intervalo. Como não há como
saber de antemão quais códigos têm esse comportamento — e ele pode aparecer em qualquer
série a qualquer momento —, a queda para janelas é automática: se a consulta aberta
falhar por qualquer motivo, a coleta repete por janelas antes de desistir.

Nenhuma observação é interpolada, arredondada ou preenchida. Observação sem valor
numérico é simplesmente omitida.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime

from comum import PAUSA, agora_iso, http_get

SGS_TUDO = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json"
SGS_JANELA = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
    "?formato=json&dataInicial={inicio}&dataFinal={fim}"
)

FONTE = "BCB/SGS"

# Ano inicial da paginação por janelas. Cobre a série mais antiga do catálogo — o IPCA
# (SGS 433) começa em 01/1980 e o saldo do SFN (20539) em 06/1988. Janela sem dado
# responde 404 e é pulada, então sobra só o custo de algumas requisições vazias no
# caminho de exceção. A janela é fechada no ano corrente.
ANO_INICIAL = 1980
JANELA_ANOS = 9  # < 10 anos, com folga, porque o limite do SGS é exclusivo na borda

_MILHAR = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


class ErroColeta(RuntimeError):
    """Falha determinística de coleta de uma série."""


# ---------------------------------------------------------------- parsing


def parse_data_bcb(texto: str) -> date:
    """Converte `dd/MM/yyyy` do SGS para date. Levanta ValueError em formato inesperado."""
    return datetime.strptime(texto.strip(), "%d/%m/%Y").date()


def parse_valor_bcb(texto: str) -> float:
    """
    Converte o valor em string do SGS para float.

    O SGS não é consistente no separador decimal. A regra aplicada é determinística:

      1. há vírgula  -> vírgula é o decimal e ponto é separador de milhar ("1.234,56");
      2. sem vírgula, mas o ponto forma grupos de três ("2.731.513") -> milhar, remove;
      3. caso contrário o ponto é o decimal ("49.75") e a string passa direto.

    A regra do item 3 é o que impede a corrupção silenciosa do caso mais comum: aplicar
    `.replace(".", "")` cegamente transformaria 49.75 em 4975.
    """
    s = texto.strip()
    if not s:
        raise ValueError("valor vazio")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif _MILHAR.match(s):
        s = s.replace(".", "")
    return float(s)


def normaliza_payload(dados: object, serie_id: str) -> list[list]:
    """
    Valida o payload do SGS e devolve [[data_iso, valor], ...] em ordem cronológica.

    Observação sem valor numérico é omitida — o SGS usa string vazia para o dado
    ainda não divulgado.
    """
    if not isinstance(dados, list):
        raise ErroColeta(f"{serie_id}: resposta não é lista (provável erro mascarado com HTTP 200)")
    if not dados:
        raise ErroColeta(f"{serie_id}: série sem observações")
    if not all(isinstance(d, dict) for d in dados):
        raise ErroColeta(f"{serie_id}: itens do payload não são objetos")

    obs: list[list] = []
    for item in dados:
        bruto = item.get("valor")
        if bruto is None or str(bruto).strip() == "":
            continue
        obs.append([parse_data_bcb(item["data"]).isoformat(), parse_valor_bcb(str(bruto))])

    if not obs:
        raise ErroColeta(f"{serie_id}: nenhuma observação com valor numérico")

    obs.sort(key=lambda o: o[0])
    return obs


# ---------------------------------------------------------------- coleta


def _janelas(hoje: date | None = None) -> list[tuple[str, str]]:
    """Janelas de menos de 10 anos para paginar séries diárias, em `dd/MM/yyyy`."""
    fim_ano = (hoje or date.today()).year
    janelas = []
    ano = ANO_INICIAL
    while ano <= fim_ano:
        ultimo = min(ano + JANELA_ANOS, fim_ano)
        janelas.append((f"01/01/{ano}", f"31/12/{ultimo}"))
        ano = ultimo + 1
    return janelas


def _baixa_aberto(codigo: int | str, serie_id: str) -> list[dict]:
    """
    Consulta sem intervalo — o caminho normal de uma série mensal, trimestral ou anual.

    Levanta `ErroColeta` em qualquer resposta que não seja uma lista não vazia de
    observações, inclusive no `{"erro":{}}` com status 200 que algumas séries devolvem.
    Quem chama decide se tenta de novo por janelas.
    """
    resp = http_get(SGS_TUDO.format(codigo=codigo))
    if resp.status_code == 406:
        raise ErroColeta(f"{serie_id}: 406 — código {codigo} inexistente ou inválido no SGS")
    if resp.status_code != 200:
        raise ErroColeta(f"{serie_id}: HTTP {resp.status_code} no SGS")
    try:
        dados = resp.json()
    except ValueError:
        raise ErroColeta(f"{serie_id}: resposta do SGS não é JSON")
    if not isinstance(dados, list) or not dados:
        # `{"erro":{}}` com status 200, ou lista vazia. Não é erro de rede: é a série
        # recusando a consulta aberta. A janela resolve.
        raise ErroColeta(f"{serie_id}: consulta sem intervalo não devolveu observações")
    return dados


def _baixa(codigo: int | str, periodicidade: str, serie_id: str) -> list[dict]:
    """
    Baixa o payload bruto do SGS.

    Série diária vai direto para a paginação, porque o SGS recusa intervalos de dez anos
    ou mais nesse caso. As demais tentam primeiro a consulta aberta e só caem para as
    janelas se ela falhar — o que cobre tanto a indisponibilidade momentânea quanto as
    séries que simplesmente não respondem sem intervalo, como a 27703.
    """
    if periodicidade != "D":
        try:
            return _baixa_aberto(codigo, serie_id)
        except ErroColeta as exc:
            if "406" in str(exc):
                raise  # código inexistente: janela nenhuma vai salvar
            print(f"         .. {serie_id}: consulta aberta falhou, tentando por janelas")
            time.sleep(PAUSA)

    acumulado: list[dict] = []
    for inicio, fim in _janelas():
        resp = http_get(SGS_JANELA.format(codigo=codigo, inicio=inicio, fim=fim))
        if resp.status_code == 404:  # janela sem dado — o SGS responde 404, não lista vazia
            time.sleep(PAUSA)
            continue
        if resp.status_code == 406:
            raise ErroColeta(f"{serie_id}: 406 — código {codigo} inexistente ou inválido no SGS")
        if resp.status_code != 200:
            raise ErroColeta(f"{serie_id}: HTTP {resp.status_code} na janela {inicio}-{fim}")
        try:
            trecho = resp.json()
        except ValueError:
            raise ErroColeta(f"{serie_id}: resposta do SGS não é JSON na janela {inicio}-{fim}")
        if isinstance(trecho, list):
            acumulado.extend(trecho)
        time.sleep(PAUSA)
    return acumulado


def coleta(serie: dict) -> dict:
    """
    Coleta uma série do SGS e devolve o payload normalizado.

    Levanta `ErroColeta` em qualquer falha — quem chama decide se cai para o cache.
    """
    codigo = serie["codigo"]
    dados = _baixa(codigo, serie.get("periodicidade", "M"), serie["serie_id"])
    obs = normaliza_payload(dados, serie["serie_id"])
    return {
        "serie_id": serie["serie_id"],
        "fonte": FONTE,
        "codigo_fonte": str(codigo),
        "unidade": serie["unidade"],
        "periodicidade": serie.get("periodicidade", "M"),
        "coletado_em": agora_iso(),
        "obs": obs,
    }
