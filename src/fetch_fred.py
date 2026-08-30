"""
Coleta das séries do FRED (inclui as séries do BIS redistribuídas pelo FRED).

Pontos da API tratados aqui:
  - exige `FRED_API_KEY`; a chave vem do ambiente (em CI, GitHub Secret) e nunca do código;
  - valor ausente é a string "." — a observação é omitida, nunca interpolada;
  - datas vêm em `yyyy-MM-dd` e já referem o primeiro dia do período;
  - séries do BIS são trimestrais, com defasagem de um a dois trimestres;
  - `400` costuma indicar `series_id` inexistente ou chave inválida.
"""

from __future__ import annotations

import os
from datetime import date, datetime

from comum import agora_iso, http_get
from fetch_bcb import ErroColeta

FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"
FONTE = "FRED"

AUSENTE = "."


def parse_data_fred(texto: str) -> date:
    """Converte `yyyy-MM-dd` do FRED para date."""
    return datetime.strptime(texto.strip(), "%Y-%m-%d").date()


def normaliza_observacoes(payload: object, serie_id: str) -> list[list]:
    """
    Valida o payload do FRED e devolve [[data_iso, valor], ...] em ordem cronológica.

    O FRED marca observação indisponível com ".". Essas linhas são descartadas —
    nenhuma lacuna é preenchida.
    """
    if not isinstance(payload, dict) or "observations" not in payload:
        raise ErroColeta(f"{serie_id}: payload do FRED sem 'observations'")

    observacoes = payload["observations"]
    if not isinstance(observacoes, list) or not observacoes:
        raise ErroColeta(f"{serie_id}: série sem observações")

    obs: list[list] = []
    for item in observacoes:
        if not isinstance(item, dict):
            raise ErroColeta(f"{serie_id}: item de observação não é objeto")
        bruto = str(item.get("value", "")).strip()
        if not bruto or bruto == AUSENTE:
            continue
        obs.append([parse_data_fred(item["date"]).isoformat(), float(bruto)])

    if not obs:
        raise ErroColeta(f"{serie_id}: nenhuma observação com valor numérico")

    obs.sort(key=lambda o: o[0])
    return obs


def chave() -> str:
    """Lê FRED_API_KEY do ambiente. Levanta ErroColeta se não estiver definida."""
    valor = os.environ.get("FRED_API_KEY")
    if not valor:
        raise ErroColeta(
            "FRED_API_KEY não definida. Defina no ambiente, em .env (fora do versionamento) "
            "ou, em CI, como GitHub Secret."
        )
    return valor


def coleta(serie: dict, api_key: str | None = None) -> dict:
    """
    Coleta uma série do FRED e devolve o payload normalizado.

    Levanta `ErroColeta` em qualquer falha — quem chama decide se cai para o cache.
    """
    codigo = serie["codigo"]
    resp = http_get(
        FRED_OBS,
        params={"series_id": codigo, "api_key": api_key or chave(), "file_type": "json"},
    )
    if resp.status_code == 400:
        raise ErroColeta(f"{serie['serie_id']}: 400 — series_id {codigo} inválido ou chave recusada")
    if resp.status_code != 200:
        raise ErroColeta(f"{serie['serie_id']}: HTTP {resp.status_code} no FRED")
    try:
        payload = resp.json()
    except ValueError:
        raise ErroColeta(f"{serie['serie_id']}: resposta do FRED não é JSON")

    obs = normaliza_observacoes(payload, serie["serie_id"])
    return {
        "serie_id": serie["serie_id"],
        "fonte": FONTE,
        "codigo_fonte": str(codigo),
        "unidade": serie["unidade"],
        "periodicidade": serie.get("periodicidade", "T"),
        "coletado_em": agora_iso(),
        "obs": obs,
    }
