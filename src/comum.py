"""
Utilidades compartilhadas do ETL: caminhos, catálogos, HTTP com retry e cache.

Nada aqui interpreta dado. Este módulo só resolve caminho, lê configuração,
faz requisição com política de retry e persiste/recupera cache bruto normalizado.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config"
DATA = RAIZ / "data"
CACHE = DATA / "_cache"
DOCS = RAIZ / "docs"
CONTENT = RAIZ / "content"

# Formato canônico — ordem das colunas definida em CLAUDE.md.
COLUNAS = ["serie_id", "data", "valor", "fonte", "codigo_fonte", "unidade", "periodicidade"]

TIMEOUT = 30
PAUSA = 0.7  # intervalo mínimo entre chamadas — o SGS devolve 429 sob rajada
TENTATIVAS = 4


# ---------------------------------------------------------------- ambiente


def carrega_env() -> None:
    """Lê `.env` da raiz, se existir. Variável já definida no ambiente tem precedência."""
    caminho = RAIZ / ".env"
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def agora_iso() -> str:
    """Timestamp UTC em ISO-8601, com segundos."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# O Brasil não adota horário de verão desde 2019, então o offset é fixo. Depender do
# banco de fusos do sistema quebraria no Windows sem o pacote tzdata instalado.
BRASILIA = timezone(timedelta(hours=-3))


def agora_brasilia() -> str:
    """Data e hora da geração no horário de Brasília, já formatada para a página."""
    return datetime.now(BRASILIA).strftime("%d/%m/%Y às %H:%M")


# ---------------------------------------------------------------- HTTP


def http_get(url: str, **kwargs: Any) -> requests.Response:
    """GET com retry e backoff exponencial. Repete em 429 e em 5xx."""
    ultima_excecao: Exception | None = None
    for tentativa in range(TENTATIVAS):
        try:
            resp = requests.get(url, timeout=TIMEOUT, **kwargs)
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                time.sleep(2**tentativa)
                continue
            return resp
        except requests.RequestException as exc:  # rede instável
            ultima_excecao = exc
            time.sleep(2**tentativa)
    raise RuntimeError(f"falha de rede em {url}: {ultima_excecao}")


# ---------------------------------------------------------------- catálogos


def carrega_catalogo(arquivo: str) -> dict:
    """Carrega um catálogo YAML de `config/`."""
    return yaml.safe_load((CONFIG / arquivo).read_text(encoding="utf-8"))


def carrega_blocos() -> dict:
    """Carrega a organização temática da página."""
    return yaml.safe_load((CONFIG / "blocos.yaml").read_text(encoding="utf-8"))


def carrega_metodologia() -> str:
    """
    Texto de `content/metodologia.md`, cru, para a página renderizar.

    É texto humano: o pipeline transporta, não escreve nem resume.
    """
    caminho = CONTENT / "metodologia.md"
    return caminho.read_text(encoding="utf-8").strip() if caminho.exists() else ""


# ---------------------------------------------------------------- cache


def caminho_cache(serie_id: str) -> Path:
    return CACHE / f"{serie_id}.json"


def le_cache(serie_id: str) -> dict | None:
    """Devolve o último payload normalizado desta série, ou None se não houver."""
    caminho = caminho_cache(serie_id)
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except ValueError:
        return None


def grava_cache(serie_id: str, payload: dict) -> None:
    """Persiste o payload normalizado. `data/_cache/` está fora do versionamento."""
    CACHE.mkdir(parents=True, exist_ok=True)
    caminho_cache(serie_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def grava_json(caminho: Path, conteudo: Any) -> None:
    """Escreve JSON UTF-8 indentado, criando o diretório se preciso."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1), encoding="utf-8")
