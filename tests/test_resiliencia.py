"""
Testes da política de falha e do guard de regressão. Nenhuma chamada de rede:
a coleta é substituída por dublês que levantam ou devolvem payload pronto.

Uso:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
