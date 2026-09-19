"""
Gera a planilha pública a partir de `data/series.parquet` e de `docs/dados.js`.

Estrutura da pasta:
  Leia-me       procedência, abrangência das fontes, conversões e séries calculadas
  Dicionário    a ficha de cada série: nome na fonte, código, tabela, unidade, cobertura
  <aba>         uma aba por aba temática da página, datas em linhas e séries em colunas,
                nos VALORES ORIGINAIS da fonte
  base_*        uma aba por base do seletor (nominal, real, pib, var1m, var12m), com as
                séries de saldo já transformadas e o sufixo padronizado na coluna
  dados_longo   o formato canônico inteiro, para quem for reprocessar

CLAUDE.md, princípio 3 da orientação: a planilha traz cada série desde a PRIMEIRA
observação da fonte, em valores originais. As abas temáticas e `dados_longo` cumprem
isso. As abas `base_*` são o acréscimo de 19/09/2026 — a orientação pede que as séries
transformadas também sejam baixáveis, com sufixos padronizados: antes só existia `_real`.

Nenhum recorte de exibição chega aqui. O gráfico pode abrir em 2007; a planilha começa
onde a fonte começa.

A planilha é gerada, nunca editada à mão. Copiada para `docs/` porque o GitHub Pages
publica apenas o conteúdo dessa pasta.

Uso:
    python src/build_xlsx.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from comum import DATA, DOCS, carrega_abas, carrega_catalogo

ARQUIVO = "monitor_endividamento.xlsx"

AZUL = "164194"

LEIA_ME = [
    ("Monitor de Crédito e Endividamento", ""),
    ("Desenvolvido por Kleber Pacheco de Castro", ""),
    ("", ""),
    (
        "Painel técnico de acompanhamento de dados públicos. Não constitui posição "
        "institucional de nenhuma entidade nem recomendação de investimento.",
        "",
    ),
    ("", ""),
    ("Abrangência das fontes", ""),
    (
        "BCB/SGS",
        "Cobre exclusivamente operações do Sistema Financeiro Nacional, exceto as séries "
        "de crédito ampliado (Tabela 1), que incluem também títulos de dívida e dívida "
        "externa. Não inclui dívida com o comércio nem com fintechs não reguladas.",
    ),
    (
        "BIS (via FRED)",
        "Cobre crédito ao setor de todas as fontes — bancos domésticos, mercado de capitais "
        "e credores externos. Os níveis são estruturalmente mais altos que os do SFN e NÃO "
        "são comparáveis com as demais abas, que cobrem o SFN.",
    ),
    ("", ""),
    ("Tratamento dos dados", ""),
    (
        "Valores originais",
        "Nenhum valor é interpolado, arredondado ou estimado. Observação sem valor "
        "divulgado na fonte é omitida. As abas temáticas e a aba dados_longo trazem cada "
        "série desde a primeira observação, na unidade original da fonte.",
    ),
    (
        "Conversão de unidade",
        "O SGS publica os saldos de crédito em R$ milhões e a página exibe em R$ bilhões. "
        "A conversão é só de exibição: ela aparece nas abas base_* e no Dicionário, nunca "
        "nas abas temáticas nem em dados_longo.",
    ),
    (
        "Séries calculadas",
        "As séries de parcela residual (terminadas em _outros), os totais por porte e por "
        "atividade econômica e a inadimplência total por porte não vêm da fonte: são "
        "calculadas pela regra declarada em config/derivadas.yaml. A coluna calculo do "
        "Dicionário traz a fórmula com os códigos envolvidos.",
    ),
    ("", ""),
    ("Abas de base transformada", ""),
    (
        "base_nominal",
        "Saldo da fonte convertido para a unidade de exibição. Sufixo _nominal.",
    ),
    (
        "base_real",
        "Saldo deflacionado pelo IPCA (SGS 433), a preços do mês mais recente do índice. "
        "A linha 'Mês-base do deflator' abaixo diz qual é. Sufixo _real.",
    ),
    (
        "base_pib",
        "Saldo dividido pelo PIB acumulado em 12 meses a valores correntes (SGS 4382), em "
        "porcentagem. Sufixo _pib.",
    ),
    (
        "base_var1m",
        "Variação percentual do valor nominal contra o mês anterior. A primeira observação "
        "de cada série fica vazia. A série NÃO é dessazonalizada, e os saldos de crédito "
        "têm sazonalidade marcada. Sufixo _var1m.",
    ),
    (
        "base_var12m",
        "Variação percentual do valor nominal contra o mesmo mês do ano anterior. Os doze "
        "primeiros meses de cada série ficam vazios, sem preenchimento. Sufixo _var12m.",
    ),
]


def _catalogo_completo() -> dict[str, dict]:
    """Catálogo inteiro, incluindo as séries calculadas."""
    series = {}
    for arquivo in ("series_bcb.yaml", "series_fred.yaml", "derivadas.yaml"):
        for serie in carrega_catalogo(arquivo)["series"]:
            series[serie["serie_id"]] = serie
    return series


def le_payload() -> dict:
    """
    Lê `docs/dados.js` de volta como JSON.

    A planilha precisa das séries JÁ transformadas, e quem as calcula é
    `src/build_dataset.py`. Recalcular aqui seria uma segunda implementação das mesmas
    quatro fórmulas — exatamente o que o pipeline evita. Então a planilha consome o
    mesmo payload que a página consome: uma fonte só para os dois artefatos.
    """
    caminho = DOCS / "dados.js"
    if not caminho.exists():
        raise SystemExit("docs/dados.js não existe. Rode `python src/build_dataset.py` antes.")
    texto = caminho.read_text(encoding="utf-8")
    inicio = texto.index("window.MONITOR = ") + len("window.MONITOR = ")
    fim = texto.rindex(";")
    return json.loads(texto[inicio:fim])


def _largura(ws, larguras: list[int]) -> None:
    for i, largura in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(i)].width = largura


def _cabecalho(ws) -> None:
    """Deixa a primeira linha em negrito azul e congela o cabeçalho."""
    for celula in ws[1]:
        celula.font = Font(bold=True, color=AZUL)
    ws.freeze_panes = "A2"


def nome_de_aba(titulo: str) -> str:
    """
    Nome de aba aceito pelo Excel: até 31 caracteres, sem `: \\ / ? * [ ]`.

    O truncamento em 31 é do Excel. A remoção dos caracteres proibidos é defensiva: um
    título de aba novo em abas.yaml não pode quebrar a geração da planilha.
    """
    limpo = re.sub(r"[:\\/?*\[\]]", "-", titulo)
    return limpo[:31]


def monta_dicionario(catalogo: dict[str, dict], manifesto: list[dict]) -> pd.DataFrame:
    """Uma linha por série coletada: identificação, procedência, conversão e cobertura."""
    linhas = []
    for entrada in manifesto:
        cfg = catalogo.get(entrada["serie_id"], {})
        fator = float(cfg.get("fator", 1))
        origem = cfg.get("unidade", entrada["unidade"])
        exibicao = cfg.get("unidade_exibicao") or origem
        linhas.append(
            {
                "serie_id": entrada["serie_id"],
                "nome_na_fonte": cfg.get("descricao_esperada", ""),
                "fonte": entrada["fonte"],
                "codigo_na_fonte": entrada["codigo_fonte"],
                "tabela_de_origem": cfg.get("tabela", ""),
                "unidade_original": origem,
                "unidade_exibida": exibicao,
                "conversao": "nenhuma" if fator == 1 else f"x {fator:g}",
                "segmento": cfg.get("segmento", ""),
                "periodicidade": entrada["periodicidade"],
                "primeira_observacao": entrada.get("inicio"),
                "ultima_observacao": entrada.get("ultima_data"),
                "n_observacoes": entrada.get("n_obs", 0),
                "calculo": cfg.get("calculo", ""),
            }
        )
    return pd.DataFrame(linhas)


def para_largo(df: pd.DataFrame, series_ids: list[str]) -> pd.DataFrame:
    """Pivota o formato longo para data x série, preservando lacunas como vazio."""
    recorte = df[df["serie_id"].isin(series_ids)]
    largo = recorte.pivot_table(index="data", columns="serie_id", values="valor", aggfunc="first")
    ordem = [s for s in series_ids if s in largo.columns]
    largo = largo[ordem].sort_index()
    largo.index = largo.index.date
    largo.index.name = "data"
    return largo.reset_index()


def tabela_da_base(payload: dict, base: str, sufixo: str) -> pd.DataFrame:
    """
    Data x série para uma das bases, direto do payload da página.

    Entram só as séries que o catálogo declara como transformáveis — na prática, os
    saldos. Uma taxa de juros ou uma inadimplência tem uma base só, a da própria fonte,
    e já está nas abas temáticas na unidade original; repeti-la aqui com o sufixo
    `_nominal` sugeriria uma transformação que não houve, e arrastaria a aba para 109
    colunas e para o ano de 1947, que é onde a série mais antiga do BIS começa.

    Coluna vazia é lacuna real — mês sem IPCA, sem PIB ou sem par de doze meses antes.
    Nada é preenchido.
    """
    colunas: dict[str, dict[str, float]] = {}
    for serie_id, serie in payload["series"].items():
        if len(serie.get("bases") or []) < 2:
            continue
        valores = serie["valores"].get(base)
        if valores is None:
            continue
        colunas[serie_id + sufixo] = {
            d: v for d, v in zip(serie["datas"], valores) if v is not None
        }
    if not colunas:
        return pd.DataFrame()
    tabela = pd.DataFrame(colunas).sort_index()
    tabela.index.name = "data"
    return tabela.reset_index()


def abas_da_pagina(payload: dict) -> list[tuple[str, list[str]]]:
    """
    Para cada aba da página, as séries que aparecem nela — na ordem dos gráficos.

    Vem do payload e não de um campo `aba` no catálogo: quem decide onde uma série
    aparece é config/abas.yaml, e duplicar isso num campo por série daria duas verdades.
    Série coletada que não entra em gráfico nenhum vai para a aba "Referência", para que
    a planilha continue trazendo tudo o que o pipeline coleta.
    """
    grupos: list[tuple[str, list[str]]] = []
    usadas: set[str] = set()
    for aba in payload["abas"]:
        ids: list[str] = []
        for grafico in aba["graficos"]:
            candidatos = list(grafico["series"])
            if grafico.get("detalhe"):
                candidatos += list(grafico["detalhe"]["por"])
            for serie_id in candidatos:
                if serie_id not in ids:
                    ids.append(serie_id)
        if ids:
            grupos.append((aba["titulo"], ids))
            usadas.update(ids)

    resto = [s for s in payload["series"] if s not in usadas]
    if resto:
        grupos.append(("Referência", sorted(resto)))
    return grupos


def main() -> int:
    caminho_parquet = DATA / "series.parquet"
    if not caminho_parquet.exists():
        print("data/series.parquet não existe. Rode `python src/build_dataset.py` antes.")
        return 1

    df = pd.read_parquet(caminho_parquet)
    manifesto = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    estado = json.loads((DATA / "estado.json").read_text(encoding="utf-8"))
    payload = le_payload()
    catalogo = _catalogo_completo()
    bases = carrega_abas()["bases"]

    destino = DATA / ARQUIVO
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        leia_me = pd.DataFrame(LEIA_ME, columns=["", ""])
        leia_me.loc[len(leia_me)] = ["", ""]
        leia_me.loc[len(leia_me)] = ["Mês-base do deflator", estado.get("base_deflator") or "—"]
        leia_me.loc[len(leia_me)] = ["Vintage do PIB", estado.get("vintage_pib") or "—"]
        leia_me.loc[len(leia_me)] = ["Gerado em (UTC)", manifesto["gerado_em"]]
        leia_me.to_excel(writer, sheet_name="Leia-me", index=False, header=False)
        ws = writer.sheets["Leia-me"]
        _largura(ws, [28, 110])
        ws["A1"].font = Font(bold=True, color=AZUL, size=14)
        for linha in ws.iter_rows(min_col=2, max_col=2):
            for celula in linha:
                celula.alignment = Alignment(wrap_text=True, vertical="top")

        dicionario = monta_dicionario(catalogo, manifesto["series"])
        dicionario.to_excel(writer, sheet_name="Dicionário", index=False)
        _largura(
            writer.sheets["Dicionário"],
            [38, 96, 12, 18, 46, 16, 18, 12, 12, 14, 20, 20, 14, 70],
        )
        _cabecalho(writer.sheets["Dicionário"])

        presentes = set(df["serie_id"])
        for titulo, ids in abas_da_pagina(payload):
            ids = [i for i in ids if i in presentes]
            if not ids:
                continue
            nome_aba = nome_de_aba(titulo)
            para_largo(df, ids).to_excel(writer, sheet_name=nome_aba, index=False)
            _largura(writer.sheets[nome_aba], [12] + [26] * len(ids))
            _cabecalho(writer.sheets[nome_aba])

        for base in bases:
            tabela = tabela_da_base(payload, base["id"], base["sufixo"])
            if tabela.empty:
                continue
            nome_aba = f"base_{base['id']}"
            tabela.to_excel(writer, sheet_name=nome_aba, index=False)
            _largura(writer.sheets[nome_aba], [12] + [30] * (len(tabela.columns) - 1))
            _cabecalho(writer.sheets[nome_aba])

        longo = df.copy()
        longo["data"] = longo["data"].dt.date
        longo.to_excel(writer, sheet_name="dados_longo", index=False)
        _largura(writer.sheets["dados_longo"], [36, 12, 14, 12, 16, 14, 14])
        _cabecalho(writer.sheets["dados_longo"])

    DOCS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(destino, DOCS / ARQUIVO)

    print(f"Escrito: data/{ARQUIVO} e docs/{ARQUIVO} ({destino.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
