"""
Valida todo código de série do catálogo contra a API de origem ANTES da coleta.

Duas perguntas por série, e nenhum código entra no pipeline sem passar nas duas:

  1. a série responde, tem observações, e qual é a última delas?
  2. o nome que a fonte dá a esse código é o que o catálogo diz esperar?

O NÍVEL 2 É NOVO EM 26/09/2026, e corrige uma afirmação errada que estava escrita aqui e
no CLAUDE.md: a de que o SGS não expõe metadados por código. Expõe. Não pela API REST
nem pelo portal de dados abertos — as duas tentativas registradas em 19/09/2026, que
falharam de verdade —, mas pelo serviço SOAP legado `FachadaWSSGS`, cuja operação
`getUltimoValorXML` devolve `<NOME>`, `<UNIDADE>` e `<PERIODICIDADE>` de qualquer código,
sem sessão de navegador e sem chave. Conferido nos 113 códigos do catálogo: todos
responderam.

Isso fecha um buraco real. Até aqui, um código trocado por outro que também responde
passava o gate e ia parar na coleta; quem o pegava eram as identidades contábeis do
`build_dataset.py` — e só quando o código trocado participava de alguma identidade. Série
que não entra em soma nenhuma não tinha nada conferindo o seu significado. Agora tem.

O nível 2 não substitui as identidades contábeis, que continuam sendo o teste mais forte:
nome certo não garante que a soma das parcelas feche no total.

POR QUE O NÍVEL 2 FALHA NUM CASO E AVISA NO OUTRO. O serviço de metadados é um SOAP
legado em `www3.bcb.gov.br`, notoriamente menos estável que a API REST. Se a
indisponibilidade dele reprovasse o catálogo, este gate passaria a ser um ponto único de
falha capaz de bloquear a atualização quinzenal de dados que estão corretos — o oposto da
política do projeto, que é não deixar a queda de uma fonte derrubar o resto. Então:

  metadados responderam e o nome DIFERE   -> FALHA. É a evidência de código errado ou
                                             renomeado na fonte, que é o que se procura.
  metadados não responderam               -> AVISO. O nível 1 passou, e ausência de
                                             evidência não é evidência de erro.

Um nome renomeado na fonte também reprova, e isso é intencional: o workflow já lista
"código de série retirado ou renomeado no SGS" entre as causas esperadas de falha, abre
issue e não publica nada. Renomeação é exatamente o tipo de mudança que uma pessoa precisa
ver antes de o painel seguir dizendo outra coisa.

A UNIDADE é registrada no relatório mas NÃO reprova. O SGS escreve "R$ (milhões)" onde o
catálogo escreve "R$ milhões", e o catálogo refina "%" em "% do PIB" onde isso é
informativo. São divergências de grafia e de precisão, não de identidade do código.

Uso:
    python src/validate_series.py                # valida tudo
    python src/validate_series.py --fonte bcb    # só BCB
    python src/validate_series.py --so-pendentes # só as marcadas validar: true

Saída: relatório na tela + config/_validacao.json. Sai com código 1 se houver falha.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comum import carrega_env, escreve_texto, http_get  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config"

SGS_DADOS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}?formato=json"
FRED_META = "https://api.stlouisfed.org/fred/series"

# Metadados por código do SGS: serviço SOAP legado, documentado no cabeçalho deste
# módulo. É o único endereço público que devolve o nome oficial de um código — a API REST
# só serve dados, e o portal de dados abertos só busca por texto livre.
SGS_METADADOS = "https://www3.bcb.gov.br/wssgs/services/FachadaWSSGS"
SGS_METADADOS_ENVELOPE = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<soapenv:Envelope xmlns:soapenv='http://schemas.xmlsoap.org/soap/envelope/'"
    " xmlns:xsd='http://www.w3.org/2001/XMLSchema'"
    " xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance'><soapenv:Body>"
    "<getUltimoValorXML soapenv:encodingStyle='http://schemas.xmlsoap.org/soap/encoding/'>"
    "<in0 xsi:type='xsd:long'>{codigo}</in0>"
    "</getUltimoValorXML></soapenv:Body></soapenv:Envelope>"
)

TIMEOUT = 30

# Intervalo entre chamadas. Subiu de 0,7s para 1,2s em 19/09/2026, junto com o catálogo
# que foi de 42 para 108 séries: a validação passou de ~35 para 103 requisições em
# rajada contínua, e o ritmo que servia para a lista curta passou a ser recusado. O SGS
# tolera rajada curta e estrangula rajada longa.
PAUSA = 1.2

# Tentativas por série diante de uma resposta que não serve — erro mascarado (200 com
# corpo que não é JSON), 400, 5xx ou falha de rede. Ver `_observacao_mais_recente`.
TENTATIVAS_VALIDACAO = 4

# Espera antes de repetir, em segundos. Progressão explícita em vez de fórmula porque o
# que importa aqui é a duração TOTAL: ~14s por série problemática, o bastante para
# atravessar uma janela de estrangulamento do SGS. A versão anterior esperava 1,4s e
# 2,8s, curto demais — em 19/09/2026 sete séries reprovaram com HTTP 400 mesmo depois
# das tentativas, todas num bloco contíguo do catálogo, que é a assinatura de throttling
# e não de código errado.
ESPERAS_VALIDACAO = (2, 4, 8)


def _get(url: str, **kwargs) -> requests.Response:
    """
    GET com retry e backoff exponencial — a mesma política da coleta.

    Delega para `comum.http_get`, que repete em 429 e também em 5xx. Ter duas
    implementações levava a um gate mais frágil que o pipeline que ele protege: um
    502 transitório do SGS reprovava a validação e derrubava o build no CI.
    """
    return http_get(url, **kwargs)


# ---------------------------------------------------------------- BCB / SGS


def _observacao_mais_recente(codigo: int | str) -> tuple[dict | None, str | None]:
    """
    Última observação da série, com retry sobre tudo o que o SGS faz sob carga.

    São três respostas diferentes para a mesma coisa — "estou estrangulando você" — e
    nenhuma delas `comum.http_get` consegue tratar sozinho:

      200 com HTML no corpo   para ele, 200 foi sucesso
      400                     para uma biblioteca HTTP genérica, 400 é erro do cliente
      read timeout            ele repete, mas levanta RuntimeError ao esgotar

    As três apareceram em 19/09/2026, em execuções seguidas, sempre em BLOCOS CONTÍGUOS
    do catálogo — que é a assinatura de estrangulamento, não de código errado: as mesmas
    séries passavam minutos antes e passavam localmente. O gate agiu certo ao não
    publicar, mas reprovar um catálogo inteiro por uma rajada, quando a política
    declarada do projeto é retry com backoff, é fragilidade e não rigor.

    O que NÃO é repetido: 406, que é código inexistente — aí não há o que esperar. E se o
    erro persistir nas quatro tentativas, a série reprova do mesmo jeito: o gate continua
    com dentes.

    Devolve (observação, erro). Um dos dois é None.
    """
    ultimo_erro = "sem resposta"
    for tentativa in range(TENTATIVAS_VALIDACAO):
        try:
            resp = _get(SGS_DADOS.format(codigo=codigo, n=1))
        except (RuntimeError, requests.RequestException) as exc:
            # `comum.http_get` levanta RuntimeError depois de esgotar as tentativas de
            # rede. Sem este `except`, um único timeout derrubava o SCRIPT INTEIRO com
            # traceback, no meio da lista, em vez de reprovar aquela série — foi o que
            # aconteceu em 19/09/2026 na série 20541 (run 35461558695). O gate tem de
            # conseguir dizer QUAIS séries falharam; morrer na primeira não é um gate,
            # é um acidente.
            ultimo_erro = f"falha de rede: {exc}"
            if tentativa < TENTATIVAS_VALIDACAO - 1:
                time.sleep(ESPERAS_VALIDACAO[tentativa])
            continue

        if resp.status_code == 406:
            return None, "406 — código inexistente ou inválido no SGS"
        if resp.status_code != 200:
            # Inclui 400, que o SGS usa para estrangular rajada longa — não só 429, como
            # o CLAUDE.md supunha. Repetir é o tratamento certo; `comum.http_get` não
            # repete 400 porque, para uma biblioteca HTTP genérica, 400 é erro do cliente.
            ultimo_erro = f"HTTP {resp.status_code}"
        else:
            try:
                dados = resp.json()
            except ValueError:
                # o SGS devolve página HTML de erro com status 200 quando está sob carga
                ultimo_erro = "resposta não é JSON (provável erro mascarado)"
                dados = None
            else:
                if isinstance(dados, list) and dados:
                    return dados[-1], None
                ultimo_erro = "série sem observações"

        if tentativa < TENTATIVAS_VALIDACAO - 1:
            time.sleep(ESPERAS_VALIDACAO[tentativa])

    return None, ultimo_erro


def _normaliza_nome(texto: str | None) -> str:
    """
    Forma comparável de um nome de série: sem variação de grafia que não muda o sentido.

    Três normalizações, cada uma por uma divergência real entre o SGS e o catálogo:
    composição Unicode (NFKC), travessão e meia-risca reduzidos a hífen simples, e espaços
    em branco colapsados. Caixa é ignorada — o SGS alterna "Total" e "total" no mesmo
    conjunto de séries.

    O que NÃO é normalizado: nada que altere palavras. Acento, pontuação e parênteses
    contam, porque é justamente numa palavra trocada que um código errado se revela.
    """
    t = unicodedata.normalize("NFKC", texto or "")
    t = t.replace("–", "-").replace("—", "-").replace("‑", "-")
    return re.sub(r"\s+", " ", t).strip().casefold()


def _metadados(codigo: int | str) -> tuple[dict | None, str | None]:
    """
    Nome, unidade e periodicidade oficiais de um código, pelo SOAP legado do SGS.

    A resposta é XML com um segundo XML escapado dentro do corpo, e o interno vem em
    ISO-8859-1 declarado no seu próprio prólogo — daí os dois `html.unescape`: um desfaz o
    escape do envelope SOAP, o outro as entidades do documento interno.

    Mesma política de retry do nível 1. Devolve (metadados, erro); um dos dois é None.
    """
    ultimo_erro = "sem resposta"
    for tentativa in range(TENTATIVAS_VALIDACAO):
        try:
            resp = _get(
                SGS_METADADOS,
                metodo="post",
                data=SGS_METADADOS_ENVELOPE.format(codigo=codigo).encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
            )
        except (RuntimeError, requests.RequestException) as exc:
            ultimo_erro = f"falha de rede: {exc}"
        else:
            if resp.status_code != 200:
                ultimo_erro = f"HTTP {resp.status_code}"
            else:
                corpo = html.unescape(html.unescape(resp.text))
                nome = re.search(r"<NOME>(.*?)</NOME>", corpo, re.S)
                if nome:
                    unidade = re.search(r"<UNIDADE>(.*?)</UNIDADE>", corpo, re.S)
                    periodicidade = re.search(r"<PERIODICIDADE>(.*?)</PERIODICIDADE>", corpo, re.S)
                    return {
                        "nome": nome.group(1).strip(),
                        "unidade": unidade.group(1).strip() if unidade else "",
                        "periodicidade": periodicidade.group(1).strip() if periodicidade else "",
                    }, None
                ultimo_erro = "resposta sem <NOME> (provável erro mascarado)"

        if tentativa < TENTATIVAS_VALIDACAO - 1:
            time.sleep(ESPERAS_VALIDACAO[tentativa])

    return None, ultimo_erro


def valida_bcb(serie: dict) -> dict:
    codigo = serie["codigo"]
    res = {"serie_id": serie["serie_id"], "fonte": "BCB/SGS", "codigo": codigo}

    ultima, erro = _observacao_mais_recente(codigo)
    if erro is not None:
        return {**res, "ok": False, "erro": erro}

    esperado = serie.get("descricao_esperada")
    res.update(
        {
            "ok": True,
            "ultima_data": ultima.get("data"),
            "ultimo_valor": ultima.get("valor"),
            "descricao_esperada": esperado,
            "tabela": serie.get("tabela", ""),
        }
    )

    # Nível 2 — ver o cabeçalho deste módulo para o motivo de a indisponibilidade do
    # serviço de metadados avisar em vez de reprovar.
    meta, erro_meta = _metadados(codigo)
    if meta is None:
        res["nome_oficial"] = None
        res["metadados"] = f"indisponível ({erro_meta})"
        return res

    res["nome_oficial"] = meta["nome"]
    res["unidade_oficial"] = meta["unidade"]
    res["periodicidade_oficial"] = meta["periodicidade"]
    res["metadados"] = "conferido"

    if _normaliza_nome(meta["nome"]) != _normaliza_nome(esperado):
        return {
            **res,
            "ok": False,
            "erro": (
                "nome na fonte não é o esperado pelo catálogo — código errado ou série "
                f"renomeada no SGS.\n           fonte:    {meta['nome']}\n"
                f"           catálogo: {esperado}"
            ),
        }
    return res


# ---------------------------------------------------------------- FRED


def valida_fred(serie: dict, api_key: str) -> dict:
    codigo = serie["codigo"]
    res = {"serie_id": serie["serie_id"], "fonte": "FRED", "codigo": codigo}

    # Mesma proteção de `_observacao_mais_recente`: falha de rede reprova a série, não
    # derruba o script. O FRED é bem mais estável que o SGS, mas a regra é a mesma.
    try:
        resp = _get(FRED_META, params={"series_id": codigo, "api_key": api_key, "file_type": "json"})
    except (RuntimeError, requests.RequestException) as exc:
        return {**res, "ok": False, "erro": f"falha de rede: {exc}"}

    if resp.status_code == 400:
        return {**res, "ok": False, "erro": "400 — series_id inexistente no FRED"}
    if resp.status_code != 200:
        return {**res, "ok": False, "erro": f"HTTP {resp.status_code}"}

    try:
        info = resp.json().get("seriess", [])
    except ValueError:
        return {**res, "ok": False, "erro": "resposta não é JSON"}
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
    elif res.get("metadados", "").startswith("indisponível"):
        # Aviso, não falha — ver o cabeçalho do módulo. Fica visível no log para que a
        # indisponibilidade prolongada do serviço de metadados não passe despercebida.
        print(f"         aviso: metadados não conferidos — {res['metadados']}")
        print(f"         nome esperado pelo catálogo: {esperado}")
    if res.get("ultima_data"):
        print(f"         última observação: {res['ultima_data']} = {res.get('ultimo_valor', '')}")


def series_do_catalogo() -> set[str]:
    """Todo `serie_id` declarado nos catálogos de coleta, independentemente da execução."""
    ids: set[str] = set()
    for arquivo in ("series_bcb.yaml", "series_fred.yaml"):
        cat = yaml.safe_load((CONFIG / arquivo).read_text(encoding="utf-8"))
        ids.update(s["serie_id"] for s in cat["series"])
    return ids


def relatorio_mesclado(
    anterior: list[dict], novos: list[dict], conhecidas: set[str] | None = None
) -> list[dict]:
    """
    Mescla os resultados desta execução com o relatório já existente.

    Uma execução parcial (`--fonte bcb`, `--so-pendentes`) não pode apagar a validação
    das séries que ela nem tentou verificar: o relatório é a evidência de que cada código
    respondeu, e a data da última observação de cada um. Entrada nova substitui a antiga
    de mesmo `serie_id`; o resto permanece.

    `conhecidas` é o catálogo inteiro, não o que rodou agora: série retirada do catálogo
    sai também do relatório. Sem isso o arquivo acumularia evidência de séries que não
    existem mais, e a planilha continuaria com o nome oficial de uma delas.
    """
    por_id = {r["serie_id"]: r for r in anterior}
    for res in novos:
        por_id[res["serie_id"]] = res
    if conhecidas is not None:
        por_id = {k: v for k, v in por_id.items() if k in conhecidas}
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

    escreve_texto(
        caminho_relatorio,
        json.dumps(
            relatorio_mesclado(anterior, resultados, series_do_catalogo()),
            ensure_ascii=False,
            indent=2,
        ),
    )

    print(f"\n{len(resultados)} série(s) verificada(s), {falhas} falha(s).")
    print("Relatório salvo em config/_validacao.json")
    if falhas:
        print("\nCorrija os códigos com falha no YAML antes de rodar a coleta.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
