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
