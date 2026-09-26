"""
Testes da política de falha e do guard de regressão. Nenhuma chamada de rede:
a coleta é substituída por dublês que levantam ou devolvem payload pronto.

Uso:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import build_dataset  # noqa: E402
import comum  # noqa: E402
import fetch_bcb  # noqa: E402

SERIE = {
    "serie_id": "serie_teste",
    "codigo": 12345,
    "unidade": "%",
    "periodicidade": "M",
}

PAYLOAD_BOM = {
    "serie_id": "serie_teste",
    "fonte": "BCB/SGS",
    "codigo_fonte": "12345",
    "unidade": "%",
    "periodicidade": "M",
    "coletado_em": "2026-08-20T12:00:00+00:00",
    "obs": [["2026-05-01", 1.5], ["2026-06-01", 1.7]],
}


class TestPoliticaDeFalha(unittest.TestCase):
    """Fonte fora do ar não pode derrubar o build nem inventar dado."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patch = mock.patch.object(comum, "CACHE", self.tmp)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_coleta_ok_grava_cache_e_marca_ok(self):
        with mock.patch.object(fetch_bcb, "coleta", return_value=PAYLOAD_BOM):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb", None)

        self.assertEqual(entrada["status"], "ok")
        self.assertEqual(entrada["n_obs"], 2)
        self.assertEqual(entrada["ultima_data"], "2026-06-01")
        self.assertEqual(payload["obs"], PAYLOAD_BOM["obs"])
        self.assertTrue(comum.caminho_cache("serie_teste").exists())

    def test_falha_com_cache_reusa_e_marca_stale(self):
        comum.grava_cache("serie_teste", PAYLOAD_BOM)

        with mock.patch.object(fetch_bcb, "coleta", side_effect=fetch_bcb.ErroColeta("503")):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb", None)

        self.assertEqual(entrada["status"], "stale")
        self.assertIn("503", entrada["motivo"])
        self.assertEqual(payload["obs"], PAYLOAD_BOM["obs"])

    def test_stale_registra_a_data_do_ultimo_dado_bom(self):
        comum.grava_cache("serie_teste", PAYLOAD_BOM)

        with mock.patch.object(fetch_bcb, "coleta", side_effect=fetch_bcb.ErroColeta("503")):
            _, entrada = build_dataset.coleta_serie(SERIE, "bcb", None)

        self.assertEqual(entrada["ultima_coleta_ok"], PAYLOAD_BOM["coletado_em"])

    def test_falha_sem_cache_marca_ausente_e_nao_levanta(self):
        with mock.patch.object(fetch_bcb, "coleta", side_effect=fetch_bcb.ErroColeta("406")):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb", None)

        self.assertIsNone(payload)
        self.assertEqual(entrada["status"], "ausente")
        self.assertEqual(entrada["n_obs"], 0)
        self.assertIsNone(entrada["ultima_coleta_ok"])

    def test_falha_de_rede_tambem_cai_para_o_cache(self):
        # `comum.http_get` levanta RuntimeError depois de esgotar os retries.
        comum.grava_cache("serie_teste", PAYLOAD_BOM)

        with mock.patch.object(fetch_bcb, "coleta", side_effect=RuntimeError("falha de rede")):
            _, entrada = build_dataset.coleta_serie(SERIE, "bcb", None)

        self.assertEqual(entrada["status"], "stale")

    def test_cache_corrompido_nao_derruba_e_vira_ausente(self):
        comum.caminho_cache("serie_teste").write_text("{ nao é json", encoding="utf-8")

        with mock.patch.object(fetch_bcb, "coleta", side_effect=fetch_bcb.ErroColeta("503")):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb", None)

        self.assertIsNone(payload)
        self.assertEqual(entrada["status"], "ausente")


class TestGuardDeRegressao(unittest.TestCase):
    """Cobertura não pode encolher em silêncio de uma execução para outra."""

    @staticmethod
    def _manifesto(*pares):
        return [
            {"serie_id": sid, "status": status, "n_obs": n}
            for sid, status, n in pares
        ]

    def test_primeira_execucao_nao_bloqueia(self):
        novo = self._manifesto(("a", "ok", 10))
        bloqueios, avisos = build_dataset.verifica_regressao(novo, [])
        self.assertEqual(bloqueios, [])
        self.assertEqual(avisos, [])

    def test_serie_que_some_bloqueia(self):
        anterior = self._manifesto(("a", "ok", 10), ("b", "ok", 10))
        novo = self._manifesto(("a", "ok", 10), ("b", "ausente", 0))
        bloqueios, _ = build_dataset.verifica_regressao(novo, anterior)
        self.assertTrue(any("b" in b for b in bloqueios))

    def test_stale_conta_como_cobertura_e_nao_bloqueia(self):
        anterior = self._manifesto(("a", "ok", 10))
        novo = self._manifesto(("a", "stale", 10))
        bloqueios, _ = build_dataset.verifica_regressao(novo, anterior)
        self.assertEqual(bloqueios, [])

    def test_serie_nova_nao_bloqueia(self):
        anterior = self._manifesto(("a", "ok", 10))
        novo = self._manifesto(("a", "ok", 11), ("b", "ok", 5))
        bloqueios, _ = build_dataset.verifica_regressao(novo, anterior)
        self.assertEqual(bloqueios, [])

    def test_perda_de_observacoes_e_apenas_aviso(self):
        anterior = self._manifesto(("a", "ok", 10))
        novo = self._manifesto(("a", "ok", 8))
        bloqueios, avisos = build_dataset.verifica_regressao(novo, anterior)
        self.assertEqual(bloqueios, [])
        self.assertTrue(any("10 -> 8" in a for a in avisos))

    def test_ganho_de_observacoes_nao_avisa(self):
        anterior = self._manifesto(("a", "ok", 10))
        novo = self._manifesto(("a", "ok", 11))
        _, avisos = build_dataset.verifica_regressao(novo, anterior)
        self.assertEqual(avisos, [])


class TestFormatoLongoJson(unittest.TestCase):
    """`data/series.json` tem de espelhar o parquet, em disposição colunar."""

    def setUp(self):
        df = build_dataset.para_formato_longo({"serie_teste": PAYLOAD_BOM})
        self.saida = build_dataset.formato_longo_json(df, "2026-08-29T00:00:00+00:00")

    def test_uma_lista_por_coluna_canonica(self):
        self.assertEqual(self.saida["formato"], "colunar")
        self.assertEqual(self.saida["colunas"], comum.COLUNAS)
        self.assertEqual(sorted(self.saida["dados"]), sorted(comum.COLUNAS))

    def test_todas_as_colunas_tem_o_mesmo_comprimento(self):
        tamanhos = {len(v) for v in self.saida["dados"].values()}
        self.assertEqual(tamanhos, {self.saida["n_observacoes"]})

    def test_a_linha_i_e_a_iesima_posicao_de_cada_lista(self):
        dados = self.saida["dados"]
        self.assertEqual(dados["data"][0], "2026-05-01")
        self.assertEqual(dados["valor"][0], 1.5)
        self.assertEqual(dados["data"][1], "2026-06-01")
        self.assertEqual(dados["valor"][1], 1.7)
        self.assertEqual(dados["codigo_fonte"][0], "12345")

    def test_reconstroi_o_dataframe_original(self):
        import pandas as pd

        refeito = pd.DataFrame(self.saida["dados"])
        self.assertEqual(list(refeito.columns), comum.COLUNAS)
        self.assertEqual(len(refeito), 2)
        self.assertEqual(refeito["valor"].tolist(), [1.5, 1.7])

    def test_valores_sao_tipos_nativos_serializaveis(self):
        import json

        json.dumps(self.saida)  # levanta se sobrar numpy
        self.assertIsInstance(self.saida["dados"]["valor"][0], float)
        self.assertIsInstance(self.saida["dados"]["serie_id"][0], str)


class TestQuebraDeLinhaDosArtefatos(unittest.TestCase):
    r"""
    Todo artefato versionado tem de sair com LF, em qualquer sistema operacional.

    O pipeline roda na máquina local (Windows) e no GitHub Actions (Ubuntu). Se a escrita
    deixar o Python traduzir `\n` para a quebra de linha da plataforma, cada alternância
    entre os dois reescreve o arquivo INTEIRO com a outra quebra — e `docs/dados.js`
    sozinho é mais de um megabyte de diff falso por atualização. `.gitattributes` é a
    segunda trava; esta é a primeira.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_escreve_texto_usa_lf(self):
        destino = self.tmp / "saida.txt"
        comum.escreve_texto(destino, "uma\nduas\ntres\n")
        self.assertNotIn(b"\r\n", destino.read_bytes())

    def test_grava_json_usa_lf(self):
        destino = self.tmp / "saida.json"
        comum.grava_json(destino, {"a": [1, 2], "b": "acentuação"})
        self.assertNotIn(b"\r\n", destino.read_bytes())
        # e continua sendo JSON UTF-8 legível
        self.assertEqual(json.loads(destino.read_text(encoding="utf-8"))["b"], "acentuação")

    def test_cria_o_diretorio_se_preciso(self):
        destino = self.tmp / "fundo" / "do" / "poco.txt"
        comum.escreve_texto(destino, "ok\n")
        self.assertEqual(destino.read_text(encoding="utf-8"), "ok\n")


if __name__ == "__main__":
    unittest.main()


class TestGuardDeAgregacao(unittest.TestCase):
    """
    O guard que impede estoque e fluxo de se misturarem (`confere_agregacao`).

    Existe por um erro que não dá exceção nenhuma: uma série de concessão que esqueça
    `agregacao: fluxo` tem o seu "% do PIB" calculado pela fórmula de estoque e sai cerca
    de doze vezes menor — um número plausível à vista, no eixo certo, com a unidade certa.
    Nenhum teste de valor pegaria isso. O que pega é a coerência declarada.
    """

    def test_o_catalogo_de_producao_esta_coerente(self):
        problemas = build_dataset.confere_agregacao(build_dataset.catalogo_completo())
        self.assertEqual(problemas, [], "\n".join(problemas))

    def test_acum12m_sem_agregacao_fluxo_e_apontado(self):
        catalogo = {"x": {"bases": ["nominal", "acum12m"]}}  # `agregacao` omitida = estoque
        problemas = build_dataset.confere_agregacao(catalogo)
        self.assertEqual(len(problemas), 1)
        self.assertIn("acum12m", problemas[0])

    def test_valor_invalido_de_agregacao_e_apontado(self):
        problemas = build_dataset.confere_agregacao({"x": {"agregacao": "flusso"}})
        self.assertEqual(len(problemas), 1)
        self.assertIn("flusso", problemas[0])

    def test_serie_de_fluxo_bem_declarada_passa(self):
        catalogo = {"x": {"agregacao": "fluxo", "bases": ["nominal", "acum12m", "pib"]}}
        self.assertEqual(build_dataset.confere_agregacao(catalogo), [])

    def test_saldo_sem_o_campo_passa(self):
        """O padrão é estoque, e é o que mantém as 94 séries de saldo válidas sem edição."""
        catalogo = {"x": {"bases": ["nominal", "real", "pib", "var1m", "var12m"]}}
        self.assertEqual(build_dataset.confere_agregacao(catalogo), [])


class TestAbaDeConcessoes(unittest.TestCase):
    """
    Coerência da aba de concessões em `config/abas.yaml`, contra o catálogo real.

    Não testa aparência; testa o que, se quebrar, produz um gráfico que mente: base
    oferecida sem todas as séries a suportarem, série de saldo entrando num gráfico de
    fluxo, ou o agregado sem o papel de total.
    """

    @classmethod
    def setUpClass(cls):
        cls.catalogo = build_dataset.catalogo_completo()
        cls.abas = {a["id"]: a for a in comum.carrega_abas()["abas"]}
        cls.graficos = {g["id"]: g for g in cls.abas["concessoes"]["graficos"]}

    def test_a_aba_existe_e_vem_logo_depois_do_saldo(self):
        ordem = list(self.abas)
        self.assertEqual(ordem.index("concessoes"), ordem.index("mercado_credito") + 1)

    def test_todo_grafico_oferece_as_seis_bases(self):
        for gid, g in self.graficos.items():
            self.assertEqual(
                g["bases"],
                ["nominal", "real", "acum12m", "pib", "var1m", "var12m"],
                f"{gid} oferece {g['bases']}",
            )

    def test_toda_serie_da_aba_e_de_fluxo(self):
        for gid, g in self.graficos.items():
            for serie_id in g["series"]:
                self.assertEqual(
                    self.catalogo[serie_id].get("agregacao"),
                    "fluxo",
                    f"{gid}/{serie_id} não é fluxo",
                )

    def test_nenhuma_serie_de_saldo_entrou_na_aba(self):
        for g in self.graficos.values():
            for serie_id in g["series"]:
                self.assertTrue(
                    serie_id.startswith("conc_"),
                    f"{serie_id} não é série de concessão",
                )

    def test_os_titulos_distinguem_saldo_de_concessao(self):
        """
        O pedido explícito: o leitor tem de saber, pelo título, qual medida está vendo.

        Vale nas duas direções — nenhum título de concessão pode dizer "Saldo", e todo
        título da aba de saldo tem de dizer.
        """
        for g in self.graficos.values():
            self.assertTrue(g["titulo"].startswith("Concessões"), g["titulo"])
        for g in self.abas["mercado_credito"]["graficos"]:
            self.assertTrue(g["titulo"].startswith("Saldo"), g["titulo"])
        self.assertEqual(self.abas["mercado_credito"]["titulo"], "Saldo do crédito")
        self.assertEqual(self.abas["concessoes"]["titulo"], "Concessões de crédito")

    def test_os_graficos_de_modalidade_marcam_o_agregado_como_total(self):
        """Nos gráficos de modalidade, a série de PJ/PF vira o total — rótulo e cor."""
        for gid, agregado in (("g25", "conc_livre_pj"), ("g26", "conc_livre_pf")):
            g = self.graficos[gid]
            self.assertEqual(g["series"][0], agregado)
            self.assertEqual(g["rotulos"][agregado], "Total")
            self.assertEqual(g["cores"][agregado], "total")

    def test_cada_grafico_espelha_o_seu_equivalente_de_saldo(self):
        """
        A aba foi pedida como réplica da de saldo. Este teste fixa o pareamento: mesmo
        número de séries e mesma sequência de papéis de cor em cada par de gráficos.
        """
        pares = [("g4", "g21"), ("g5", "g22"), ("g6", "g23"), ("g7", "g24"), ("g8", "g25"), ("g9", "g26")]
        saldo = {g["id"]: g for g in self.abas["mercado_credito"]["graficos"]}
        for gid_saldo, gid_conc in pares:
            a, b = saldo[gid_saldo], self.graficos[gid_conc]
            self.assertEqual(
                len(a["series"]), len(b["series"]), f"{gid_saldo} x {gid_conc}: nº de séries"
            )
            papeis = lambda g: [  # noqa: E731
                (g.get("cores") or {}).get(s) or self.catalogo[s].get("cor") for s in g["series"]
            ]
            self.assertEqual(papeis(a), papeis(b), f"{gid_saldo} x {gid_conc}: papéis de cor")
