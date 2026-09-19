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

# Tentativas por requisição diante de uma resposta que não serve — erro mascarado
# (200 com corpo que não é JSON), 400, 5xx. Ver `_pede_json`.
TENTATIVAS_PAYLOAD = 4

# Espera antes de repetir, em segundos. Mesma progressão de `validate_series`, e pelo
# mesmo motivo: o que importa é a duração total (~14s), suficiente para atravessar uma
# janela de estrangulamento do SGS. Backoff curto não adianta contra throttling.
ESPERAS_PAYLOAD = (2, 4, 8)

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


def _pede_json(url: str, serie_id: str, onde: str) -> list | None:
    """
    GET no SGS, com retry sobre o erro MASCARADO, devolvendo a lista de observações.

    Três resultados possíveis:
      lista  -> o payload, podendo ser vazio
      None   -> 404, que no SGS significa "intervalo sem dado" e não erro
      exceção -> 406 (código inexistente) ou falha que persistiu nas tentativas

    O retry existe porque o SGS, sob carga, responde 200 com uma página HTML de erro no
    corpo. `comum.http_get` não consegue repetir nesse caso — para ele, 200 foi sucesso.
    Só quem conhece o formato esperado da resposta pode decidir repetir, e é aqui.

    Isto derrubou a publicação em 19/09/2026 (run 35460622823): a consulta aberta de dez
    séries falhou durante uma instabilidade do BCB, a coleta caiu para janelas, e a
    PRIMEIRA janela devolveu HTML com status 200. Sem retry, uma janela ruim abortava a
    série inteira — e como `data/_cache/` não é versionado, no CI não há cache para
    amparar: a série ia direto para `ausente` e disparava o guard de regressão.

    Um 404 continua sendo pulado sem retry: é resposta legítima, não falha.
    """
    ultimo = "sem resposta"
    for tentativa in range(TENTATIVAS_PAYLOAD):
        resp = http_get(url)
        if resp.status_code == 404:
            return None
        if resp.status_code == 406:
            raise ErroColeta(f"{serie_id}: 406 — código inexistente ou inválido no SGS")
        if resp.status_code != 200:
            # Inclui 400, que o SGS usa para estrangular rajada longa — não só 429.
            ultimo = f"HTTP {resp.status_code}"
        else:
            try:
                dados = resp.json()
            except ValueError:
                ultimo = "resposta do SGS não é JSON (provável erro mascarado)"
            else:
                if isinstance(dados, list):
                    return dados
                # `{"erro":{}}` com status 200: pode ser a série recusando a consulta
                # aberta (caso da 27703) ou instabilidade. Repetir distingue os dois.
                ultimo = "payload não é lista de observações"

        if tentativa < TENTATIVAS_PAYLOAD - 1:
            time.sleep(ESPERAS_PAYLOAD[tentativa])

    raise ErroColeta(f"{serie_id}: {ultimo} em {onde}")


def _baixa_aberto(codigo: int | str, serie_id: str) -> list[dict]:
    """
    Consulta sem intervalo — o caminho normal de uma série mensal, trimestral ou anual.

    Levanta `ErroColeta` se, depois das tentativas, não vier uma lista não vazia de
    observações. Quem chama decide se tenta de novo por janelas.
    """
    dados = _pede_json(SGS_TUDO.format(codigo=codigo), serie_id, "consulta sem intervalo")
    if not dados:
        raise ErroColeta(f"{serie_id}: consulta sem intervalo não devolveu observações")
    return dados


def _baixa(codigo: int | str, periodicidade: str, serie_id: str) -> list[dict]:
    """
    Baixa o payload bruto do SGS.

    Série diária vai direto para a paginação, porque o SGS recusa intervalos de dez anos
    ou mais nesse caso. As demais tentam primeiro a consulta aberta e só caem para as
    janelas se ela falhar — o que cobre tanto a indisponibilidade momentânea quanto as
    séries que simplesmente não respondem sem intervalo, como a 27703.

    Uma janela que falha depois das tentativas aborta a série inteira, de propósito: a
    alternativa seria devolver a série com um buraco silencioso no meio, e dado faltando
    sem aviso é o que este projeto não pode fazer. Janela vazia (404) é outra coisa, e é
    simplesmente pulada.
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
        trecho = _pede_json(
            SGS_JANELA.format(codigo=codigo, inicio=inicio, fim=fim),
            serie_id,
            f"janela {inicio}-{fim}",
        )
        if trecho:
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
