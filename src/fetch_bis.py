"""
Coleta das séries do BIS, direto na API SDMX (https://stats.bis.org/api/v2).

Até 30/09/2026 estas séries vinham do FRED, que as redistribui com meses de atraso em
relação à divulgação do BIS. A fonte primária entrega o mesmo dado mais cedo e sem chave
de API. Ver o cabeçalho de `config/series_bis.yaml`.

Pontos da API tratados aqui:
  - o código de cada série é a chave SDMX do dataflow WS_TC (ex.: `Q.BR.H.A.M.770.A`);
  - pede-se CSV, que traz o nome da série (TITLE_TS) em cada linha;
  - o período vem como `yyyy-Qn` e é convertido para o primeiro dia do trimestre;
  - observação sem valor é omitida, nunca interpolada;
  - `404` significa chave inexistente no dataflow.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from comum import BIS_DADOS, agora_iso, http_get
from fetch_bcb import CodigoInexistente, ErroColeta, FonteIndisponivel, SerieVazia

FONTE = "BIS"


def parse_periodo_bis(texto: str) -> date:
    """Converte `yyyy-Qn` do BIS para o primeiro dia do trimestre."""
    ano, trimestre = texto.strip().split("-Q")
    return date(int(ano), 3 * (int(trimestre) - 1) + 1, 1)


def le_csv(texto: str, serie_id: str) -> list[dict]:
    """
    Linhas do CSV do BIS. Levanta `FonteIndisponivel` se o corpo não for o CSV esperado:
    resposta 200 com corpo que não é o formato pedido é o erro mascarado, não código errado.
    """
    linhas = list(csv.DictReader(io.StringIO(texto)))
    if not linhas or "TIME_PERIOD" not in linhas[0] or "OBS_VALUE" not in linhas[0]:
        raise FonteIndisponivel(f"{serie_id}: resposta do BIS não é o CSV esperado")
    return linhas


def normaliza_observacoes(linhas: list[dict], serie_id: str) -> list[list]:
    """Devolve [[data_iso, valor], ...] em ordem cronológica, sem as linhas sem valor."""
    obs: list[list] = []
    for linha in linhas:
        bruto = (linha.get("OBS_VALUE") or "").strip()
        if not bruto or bruto.upper() == "NAN":
            continue
        obs.append([parse_periodo_bis(linha["TIME_PERIOD"]).isoformat(), float(bruto)])

    if not obs:
        raise SerieVazia(f"{serie_id}: nenhuma observação com valor numérico")

    obs.sort(key=lambda o: o[0])
    return obs


def pede_csv(codigo: str, serie_id: str, **params) -> list[dict]:
    """GET na API SDMX do BIS em CSV. Levanta ErroColeta em qualquer resposta inválida."""
    resp = http_get(BIS_DADOS.format(codigo=codigo), params={"format": "csv", **params})
    if resp.status_code == 404:
        raise CodigoInexistente(f"{serie_id}: 404 — chave {codigo} inexistente no BIS")
    if resp.status_code != 200:
        raise FonteIndisponivel(f"{serie_id}: HTTP {resp.status_code} no BIS")
    return le_csv(resp.text, serie_id)


def coleta(serie: dict) -> dict:
    """
    Coleta uma série do BIS e devolve o payload normalizado.

    Levanta `ErroColeta` em qualquer falha — quem chama decide se cai para o cache.
    """
    codigo = serie["codigo"]
    obs = normaliza_observacoes(pede_csv(codigo, serie["serie_id"]), serie["serie_id"])
    return {
        "serie_id": serie["serie_id"],
        "fonte": FONTE,
        "codigo_fonte": str(codigo),
        "unidade": serie["unidade"],
        "periodicidade": serie.get("periodicidade", "T"),
        "coletado_em": agora_iso(),
        "obs": obs,
    }
