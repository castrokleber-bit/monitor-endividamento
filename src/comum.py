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

# Endereços das fontes. Ficam aqui, num lugar só, porque a coleta (`fetch_*.py`) e o gate
# (`validate_series.py`) consultam as mesmas APIs; duas cópias do mesmo endereço divergem
# no dia em que a fonte mudar de caminho.
SGS_TUDO = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json"
SGS_JANELA = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
    "?formato=json&dataInicial={inicio}&dataFinal={fim}"
)
SGS_ULTIMOS = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}?formato=json"
)
BIS_DADOS = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0/{codigo}"

TIMEOUT = 30

# Intervalo entre chamadas, o mesmo na coleta e na validação. Subiu de 0,7s para 1,2s em
# 19/09/2026, quando o catálogo foi de 42 para 108 séries: com mais de cem requisições em
# rajada contínua, o SGS passou a estrangular o ritmo antigo. 1,2s é o valor que o
# CLAUDE.md registra como seguro para esse volume.
PAUSA = 1.2

TENTATIVAS = 4


class ErroDeRede(RuntimeError):
    """
    A fonte não respondeu depois de todas as tentativas de `http_get`.

    Subclasse de RuntimeError para que todo `except RuntimeError` já existente continue
    pegando. Existe para que quem conta falhas seguidas de uma fonte (o disjuntor da
    coleta e o da validação) distinga "a fonte não respondeu" de "o código está errado".
    """


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


def http_get(url: str, metodo: str = "get", **kwargs: Any) -> requests.Response:
    """
    Requisição com retry e backoff exponencial. Repete em 429 e em 5xx.

    Esgotadas as tentativas, levanta `ErroDeRede` com o último status HTTP ou a última
    exceção de rede na mensagem — é o que aparece no `motivo` do manifesto.

    `metodo` existe por um único caso: o serviço de metadados do SGS é SOAP e só atende
    POST (ver `validate_series._metadados`). Uma segunda função de HTTP daria duas
    políticas de retry no projeto, que é o problema que esta função já foi criada para
    resolver. O padrão continua sendo GET.
    """
    ultimo = "sem resposta"
    for tentativa in range(TENTATIVAS):
        try:
            resp = requests.request(metodo, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:  # rede instável
            ultimo = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code != 429 and not 500 <= resp.status_code < 600:
                return resp
            ultimo = f"HTTP {resp.status_code}"
        # Sem espera depois da última tentativa: não há o que esperar, e o erro sai já.
        if tentativa < TENTATIVAS - 1:
            time.sleep(2**tentativa)
    raise ErroDeRede(f"falha de rede em {url}: {ultimo} após {TENTATIVAS} tentativas")


# ---------------------------------------------------------------- catálogos


def carrega_catalogo(arquivo: str) -> dict:
    """Carrega um catálogo YAML de `config/`."""
    return yaml.safe_load((CONFIG / arquivo).read_text(encoding="utf-8"))


def carrega_abas() -> dict:
    """Carrega a organização em abas da página."""
    return yaml.safe_load((CONFIG / "abas.yaml").read_text(encoding="utf-8"))


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
    escreve_texto(
        caminho_cache(serie_id), json.dumps(payload, ensure_ascii=False, indent=1)
    )


def escreve_texto(caminho: Path, conteudo: str) -> None:
    """
    Escreve texto UTF-8 com quebra de linha LF, sempre.

    `newline=""` desliga a tradução automática do Python, que no Windows transformaria
    cada `
` em `
`. Sem isso, os artefatos versionados saem com CRLF quando o
    pipeline roda na máquina local e com LF quando roda no GitHub Actions (Ubuntu) — e
    cada alternância entre os dois produz um diff do arquivo INTEIRO, que em
    `docs/dados.js` é mais de um megabyte de ruído por atualização.
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as arquivo:
        arquivo.write(conteudo)


def grava_json(caminho: Path, conteudo: Any) -> None:
    """Escreve JSON UTF-8 indentado, criando o diretório se preciso."""
    escreve_texto(caminho, json.dumps(conteudo, ensure_ascii=False, indent=1))
