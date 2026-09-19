"""
Testes do gate de validação — a política de retry sobre o erro mascarado do SGS.

Sem rede: as respostas HTTP são dublês.

O caso que estes testes protegem aconteceu em 19/09/2026. Dezesseis séries consecutivas
reprovaram com "resposta não é JSON" numa execução do CI, e as mesmas dezesseis tinham
passado na execução anterior e passavam localmente — a API do BCB estava instável. O gate
agiu certo ao não publicar dado parcial, mas reprovar o catálogo inteiro por uma rajada
transitória é fragilidade, não rigor: a política declarada do projeto é retry com backoff.

O equilíbrio que os testes fixam: repete o que é transitório, NÃO repete o que é
definitivo (406), e continua reprovando se o erro persistir.

Uso:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import validate_series  # noqa: E402

SERIE = {"serie_id": "serie_teste", "codigo": 21090, "descricao_esperada": "Série de teste"}


class RespostaFalsa:
    """Dublê de `requests.Response` com só o que `valida_bcb` consulta."""

    def __init__(self, status_code: int, payload=None, texto_cru: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self._texto_cru = texto_cru

    def json(self):
        if self._texto_cru is not None:
            raise ValueError("não é JSON")
        return self._payload


OBS = [{"data": "01/07/2026", "valor": "2.48"}]

MASCARADO = RespostaFalsa(200, texto_cru="<!doctype html><html>erro</html>")
VAZIO = RespostaFalsa(200, payload=[])
BOM = RespostaFalsa(200, payload=OBS)


class TestRetryDoErroMascarado(unittest.TestCase):
    def setUp(self):
        # Sem espera real entre tentativas: o teste verifica a política, não o relógio.
        self.sleep = mock.patch.object(validate_series.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    def _com_respostas(self, respostas):
        return mock.patch.object(validate_series, "_get", side_effect=respostas)

    def test_html_com_status_200_e_repetido_e_pode_passar(self):
        """O caso real: a primeira tentativa pega a rajada, a segunda pega o dado."""
        with self._com_respostas([MASCARADO, BOM]) as get:
            res = validate_series.valida_bcb(SERIE)
        self.assertTrue(res["ok"])
        self.assertEqual(res["ultima_data"], "01/07/2026")
        self.assertEqual(get.call_count, 2)

    def test_lista_vazia_tambem_e_repetida(self):
        with self._com_respostas([VAZIO, BOM]):
            self.assertTrue(validate_series.valida_bcb(SERIE)["ok"])

    def test_erro_de_servidor_e_repetido(self):
        with self._com_respostas([RespostaFalsa(502), BOM]):
            self.assertTrue(validate_series.valida_bcb(SERIE)["ok"])

    def test_erro_persistente_continua_reprovando(self):
        """O gate não pode virar carimbo: erro em todas as tentativas reprova."""
        with self._com_respostas([MASCARADO] * validate_series.TENTATIVAS_VALIDACAO) as get:
            res = validate_series.valida_bcb(SERIE)
        self.assertFalse(res["ok"])
        self.assertIn("não é JSON", res["erro"])
        self.assertEqual(get.call_count, validate_series.TENTATIVAS_VALIDACAO)

    def test_406_nao_e_repetido(self):
        """Código inexistente é definitivo — insistir só gasta tempo do CI."""
        with self._com_respostas([RespostaFalsa(406), BOM]) as get:
            res = validate_series.valida_bcb(SERIE)
        self.assertFalse(res["ok"])
        self.assertIn("406", res["erro"])
        self.assertEqual(get.call_count, 1)

    def test_passa_de_primeira_sem_dormir(self):
        with self._com_respostas([BOM]) as get:
            self.assertTrue(validate_series.valida_bcb(SERIE)["ok"])
        self.assertEqual(get.call_count, 1)
        self.sleep.assert_not_called()

    def test_backoff_cresce_entre_tentativas(self):
        with self._com_respostas([MASCARADO] * validate_series.TENTATIVAS_VALIDACAO):
            validate_series.valida_bcb(SERIE)
        esperas = [c.args[0] for c in self.sleep.call_args_list]
        self.assertEqual(len(esperas), validate_series.TENTATIVAS_VALIDACAO - 1)
        self.assertEqual(esperas, sorted(esperas))
        self.assertLess(sum(esperas), 10)  # o gate não pode virar uma espera longa


if __name__ == "__main__":
    unittest.main()


class TestRetryNaColeta(unittest.TestCase):
    """
    A mesma política de retry, no caminho da COLETA.

    O caso real, run 35460622823 de 19/09/2026: a consulta aberta de dez séries do
    crédito ampliado falhou durante uma instabilidade do BCB, a coleta caiu para janelas
    de data, e a primeira janela devolveu HTML com status 200. Sem retry, aquela janela
    abortava a série inteira. Como `data/_cache/` não é versionado, no CI não há cache
    para amparar: as dez foram para `ausente` e dispararam o guard de regressão, que
    parou a publicação com código 2.
    """

    def setUp(self):
        import fetch_bcb

        self.fetch_bcb = fetch_bcb
        mock.patch.object(fetch_bcb.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    def _com(self, respostas):
        return mock.patch.object(self.fetch_bcb, "http_get", side_effect=respostas)

    def test_html_com_status_200_e_repetido(self):
        with self._com([MASCARADO, BOM]) as get:
            self.assertEqual(self.fetch_bcb._pede_json("url", "s", "onde"), OBS)
        self.assertEqual(get.call_count, 2)

    def test_404_e_janela_vazia_e_nao_falha(self):
        """404 no SGS é intervalo sem dado, não erro. Não repete e não aborta."""
        with self._com([RespostaFalsa(404)]) as get:
            self.assertIsNone(self.fetch_bcb._pede_json("url", "s", "janela"))
        self.assertEqual(get.call_count, 1)

    def test_406_nao_e_repetido(self):
        with self._com([RespostaFalsa(406), BOM]) as get:
            with self.assertRaises(self.fetch_bcb.ErroColeta):
                self.fetch_bcb._pede_json("url", "s", "onde")
        self.assertEqual(get.call_count, 1)

    def test_erro_persistente_aborta_a_serie(self):
        """
        Falha que persiste TEM de abortar: devolver a série com um buraco silencioso
        no meio é exatamente o que este projeto não pode fazer.
        """
        n = self.fetch_bcb.TENTATIVAS_PAYLOAD
        with self._com([MASCARADO] * n) as get:
            with self.assertRaises(self.fetch_bcb.ErroColeta) as ctx:
                self.fetch_bcb._pede_json("url", "serie_x", "janela 1980-1989")
        self.assertIn("janela 1980-1989", str(ctx.exception))
        self.assertEqual(get.call_count, n)

    def test_erro_mascarado_da_27703_ainda_cai_para_janelas(self):
        """
        A série 27703 recusa a consulta aberta de forma permanente, devolvendo
        `{"erro":{}}`. Depois das tentativas, `_baixa_aberto` levanta e `_baixa` cai para
        as janelas — o comportamento que fez a série funcionar. O retry não pode ter
        quebrado isso.
        """
        erro_da_27703 = RespostaFalsa(200, payload={"erro": {}})
        n = self.fetch_bcb.TENTATIVAS_PAYLOAD
        with self._com([erro_da_27703] * n):
            with self.assertRaises(self.fetch_bcb.ErroColeta):
                self.fetch_bcb._baixa_aberto(27703, "inad_porte_mpme")

    def test_janela_boa_depois_de_janela_vazia_entra_no_resultado(self):
        janelas = len(self.fetch_bcb._janelas())
        respostas = [MASCARADO] * self.fetch_bcb.TENTATIVAS_PAYLOAD  # consulta aberta falha
        respostas += [RespostaFalsa(404)] * (janelas - 1)  # janelas antigas sem dado
        respostas += [BOM]  # a última janela traz a série
        with self._com(respostas):
            self.assertEqual(self.fetch_bcb._baixa(28183, "M", "amplo_total"), OBS)
