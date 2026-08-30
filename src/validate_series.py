"""
Valida todo código de série do catálogo contra a API de origem ANTES da coleta.

Roda em dois níveis:
  1. Dados  — a série responde? Tem observações? Qual o intervalo e o último valor?
  2. Nome   — o título registrado na fonte bate com `descricao_esperada`?

Nenhum código entra no pipeline sem passar no nível 1. O nível 2 é informativo:
imprime o nome oficial para conferência humana e sinaliza divergência.

Uso:
    python src/validate_series.py                # valida tudo
    python src/validate_series.py --fonte bcb    # só BCB
    python src/validate_series.py --so-pendentes # só as marcadas validar: true

Saída: relatório na tela + config/_validacao.json. Sai com código 1 se houver falha.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comum import carrega_env, http_get  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config"

SGS_DADOS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}?formato=json"
SGS_META = "https://dadosabertos.bcb.gov.br/api/3/action/package_search"
FRED_META = "https://api.stlouisfed.org/fred/series"

TIMEOUT = 30
PAUSA = 0.7  # intervalo mínimo entre chamadas — o SGS devolve 429 sob rajada


def _get(url: str, **kwargs) -> requests.Response:
    """
    GET com retry e backoff exponencial — a mesma política da coleta.

    Delega para `comum.http_get`, que repete em 429 e também em 5xx. Ter duas
    implementações levava a um gate mais frágil que o pipeline que ele protege: um
    502 transitório do SGS reprovava a validação e derrubava o build no CI.
    """
    return http_get(url, **kwargs)


# ---------------------------------------------------------------- BCB / SGS


def valida_bcb(serie: dict) -> dict:
    codigo = serie["codigo"]
    res = {"serie_id": serie["serie_id"], "fonte": "BCB/SGS", "codigo": codigo}

    resp = _get(SGS_DADOS.format(codigo=codigo, n=1))
    if resp.status_code == 406:
        return {**res, "ok": False, "erro": "406 — código inexistente ou inválido no SGS"}
    if resp.status_code != 200:
        return {**res, "ok": False, "erro": f"HTTP {resp.status_code}"}

    try:
        dados = resp.json()
    except ValueError:
        # o SGS às vezes devolve página HTML de erro com status 200
        return {**res, "ok": False, "erro": "resposta não é JSON (provável erro mascarado)"}

    if not isinstance(dados, list) or not dados:
        return {**res, "ok": False, "erro": "série sem observações"}

    ultima = dados[-1]
    res.update({"ok": True, "ultima_data": ultima.get("data"), "ultimo_valor": ultima.get("valor")})

    # nome oficial, via portal de dados abertos (CKAN). Best effort.
    try:
        meta = _get(SGS_META, params={"q": str(codigo), "rows": 5}).json()
        titulos = [r.get("title", "") for r in meta.get("result", {}).get("results", [])]
        casado = next((t for t in titulos if str(codigo) in json.dumps(titulos) and t), None)
        res["nome_oficial"] = casado or (titulos[0] if titulos else None)
    except Exception:
        res["nome_oficial"] = None

    return res


# ---------------------------------------------------------------- FRED


def valida_fred(serie: dict, api_key: str) -> dict:
    codigo = serie["codigo"]
    res = {"serie_id": serie["serie_id"], "fonte": "FRED", "codigo": codigo}

    resp = _get(FRED_META, params={"series_id": codigo, "api_key": api_key, "file_type": "json"})
    if resp.status_code == 400:
        return {**res, "ok": False, "erro": "400 — series_id inexistente no FRED"}
    if resp.status_code != 200:
        return {**res, "ok": False, "erro": f"HTTP {resp.status_code}"}

    info = resp.json().get("seriess", [])
    if not info:
        return {**res, "ok": False, "erro": "série não encontrada"}

    s = info[0]
    return {
        **res,
        "ok": True,
        "nome_oficial": s.get("title"),
        "unidade_oficial": s.get("units"),
        "frequencia_oficial": s.get("frequency_short"),
        "ultima_data": s.get("observation_end"),
    }


# ---------------------------------------------------------------- relatório


def imprime(res: dict, esperado: str | None) -> None:
    marca = "OK  " if res["ok"] else "FALHA"
    print(f"[{marca}] {res['codigo']:<12} {res['serie_id']}")
    if not res["ok"]:
        print(f"         -> {res['erro']}")
        return
    if res.get("nome_oficial"):
        print(f"         nome na fonte: {res['nome_oficial']}")
        if esperado and esperado.lower()[:30] not in (res["nome_oficial"] or "").lower():
            print("         !! divergente da descricao_esperada — conferir manualmente")
    if res.get("ultima_data"):
        print(f"         última observação: {res['ultima_data']} = {res.get('ultimo_valor', '')}")


def relatorio_mesclado(anterior: list[dict], novos: list[dict]) -> list[dict]:
    """
    Mescla os resultados desta execução com o relatório já existente.

    Uma execução parcial (`--fonte bcb`, `--so-pendentes`) não pode apagar a validação
    das séries que ela nem tentou verificar: o relatório é a evidência de conferência
    manual dos nomes oficiais, e `build_xlsx.py` tira dele a coluna `nome_oficial` do
    Dicionário. Entrada nova substitui a antiga de mesmo `serie_id`; o resto permanece.
    """
    por_id = {r["serie_id"]: r for r in anterior}
    for res in novos:
        por_id[res["serie_id"]] = res
    return list(por_id.values())


def main() -> int:
    carrega_env()  # a chave pode vir do ambiente ou de .env, como no build_dataset

    ap = argparse.ArgumentParser()
    ap.add_argument("--fonte", choices=["bcb", "fred", "todas"], default="todas")
    ap.add_argument("--so-pendentes", action="store_true", help="apenas séries com validar: true")
    args = ap.parse_args()

    catalogos = []
    if args.fonte in ("bcb", "todas"):
        catalogos.append(("bcb", CONFIG / "series_bcb.yaml"))
    if args.fonte in ("fred", "todas"):
        catalogos.append(("fred", CONFIG / "series_fred.yaml"))

    fred_key = os.environ.get("FRED_API_KEY")
    resultados, falhas = [], 0

    for nome_fonte, caminho in catalogos:
        cat = yaml.safe_load(caminho.read_text(encoding="utf-8"))
        series = cat["series"]
        if args.so_pendentes:
            series = [s for s in series if s.get("validar")]

        print(f"\n=== {cat['fonte']} — {len(series)} série(s) ===\n")

        if nome_fonte == "fred" and not fred_key:
            # Pular em silêncio faria o gate aprovar um estado que o princípio 3 proíbe:
            # série entrando no pipeline sem validação. O erro só apareceria na coleta,
            # minutos depois. Falha aqui, alto e cedo.
            print("FALHA — FRED_API_KEY não definida; as séries do FRED não foram validadas.")
            print("  Em CI: cadastre o Secret de repositório FRED_API_KEY")
            print("         (Settings > Secrets and variables > Actions > aba Secrets).")
            print("  Local: exporte a variável ou grave em .env na raiz.")
            print("  Para validar só o BCB de propósito, use --fonte bcb.\n")
            falhas += len(series)
            continue

        for s in series:
            res = valida_bcb(s) if nome_fonte == "bcb" else valida_fred(s, fred_key)
            imprime(res, s.get("descricao_esperada"))
            resultados.append(res)
            falhas += 0 if res["ok"] else 1
            time.sleep(PAUSA)

    caminho_relatorio = CONFIG / "_validacao.json"
    anterior = []
    if caminho_relatorio.exists():
        try:
            anterior = json.loads(caminho_relatorio.read_text(encoding="utf-8"))
        except ValueError:
            anterior = []

    caminho_relatorio.write_text(
        json.dumps(relatorio_mesclado(anterior, resultados), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n{len(resultados)} série(s) verificada(s), {falhas} falha(s).")
    print("Relatório salvo em config/_validacao.json")
    if falhas:
        print("\nCorrija os códigos com falha no YAML antes de rodar a coleta.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
