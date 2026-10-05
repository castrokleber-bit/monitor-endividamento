"""
Testes de PARSING e normalização da coleta. Sem rede.

O que protegem: o decimal brasileiro do SGS, a data `dd/MM/yyyy`, a recusa de payload
mascarado (HTML com status 200, `{"erro":{}}`, lista vazia), a paginação por janelas, o
o CSV do BIS com trimestre `yyyy-Qn` e valor vazio, e o formato longo canônico.

Renomeado de test_transformacoes.py em 19/09/2026, quando nasceu `src/transformacoes.py`
e o nome antigo passou a apontar para a coisa errada. As seis bases do seletor são
testadas em tests/test_bases.py.

Uso:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import fetch_bcb  # noqa: E402
import fetch_bis  # noqa: E402
from build_dataset import para_formato_longo  # noqa: E402
from comum import COLUNAS  # noqa: E402


class TestValorBcb(unittest.TestCase):
    """O SGS alterna o separador decimal entre séries. A regra tem de cobrir os dois."""

    def test_ponto_e_decimal_quando_nao_ha_virgula(self):
        # Caso mais comum. Aplicar `.replace(".", "")` cegamente daria 4975.
        self.assertEqual(fetch_bcb.parse_valor_bcb("49.75"), 49.75)

    def test_virgula_e_decimal_com_ponto_de_milhar(self):
        self.assertEqual(fetch_bcb.parse_valor_bcb("1.234,56"), 1234.56)

    def test_virgula_e_decimal_sem_milhar(self):
        self.assertEqual(fetch_bcb.parse_valor_bcb("0,5"), 0.5)

    def test_ponto_e_milhar_quando_forma_grupos_de_tres(self):
        self.assertEqual(fetch_bcb.parse_valor_bcb("2.731.513"), 2731513.0)

    def test_um_ponto_so_com_tres_casas_e_decimal(self):
        """
        Um ponto sozinho é ambíguo; sem vírgula na string, é decimal.

        Até 04/10/2026 "0.125" virava 125 e "12.345" virava 12345: a regra de milhar
        aceitava um grupo só. O SGS usa ponto como decimal em todo o catálogo.
        """
        self.assertEqual(fetch_bcb.parse_valor_bcb("0.125"), 0.125)
        self.assertEqual(fetch_bcb.parse_valor_bcb("12.345"), 12.345)
        self.assertEqual(fetch_bcb.parse_valor_bcb("-4.125"), -4.125)

    def test_um_ponto_so_com_virgula_e_milhar(self):
        self.assertEqual(fetch_bcb.parse_valor_bcb("12.345,6"), 12345.6)

    def test_milhar_com_varios_grupos_e_negativo(self):
        self.assertEqual(fetch_bcb.parse_valor_bcb("-1.234.567"), -1234567.0)

    def test_virgula_fora_do_formato_brasileiro_falha(self):
        """Vírgula com milhar mal formado não é adivinhada: levanta."""
        for texto in ("1,234.56", "12.34,5", "1,2,3"):
            with self.assertRaises(ValueError, msg=texto):
                fetch_bcb.parse_valor_bcb(texto)

    def test_inteiro_simples(self):
        self.assertEqual(fetch_bcb.parse_valor_bcb("2731513"), 2731513.0)

    def test_negativo(self):
        self.assertEqual(fetch_bcb.parse_valor_bcb("-1,25"), -1.25)

    def test_espaco_em_volta(self):
        self.assertEqual(fetch_bcb.parse_valor_bcb("  3.14  "), 3.14)

    def test_vazio_falha(self):
        with self.assertRaises(ValueError):
            fetch_bcb.parse_valor_bcb("   ")


class TestDataBcb(unittest.TestCase):
    def test_formato_brasileiro(self):
        self.assertEqual(fetch_bcb.parse_data_bcb("01/06/2026"), date(2026, 6, 1))

    def test_formato_iso_falha(self):
        with self.assertRaises(ValueError):
            fetch_bcb.parse_data_bcb("2026-06-01")


class TestPayloadBcb(unittest.TestCase):
    def test_normaliza_e_ordena(self):
        obs = fetch_bcb.normaliza_payload(
            [
                {"data": "01/07/2026", "valor": "5.81"},
                {"data": "01/06/2026", "valor": "5.79"},
            ],
            "x",
        )
        self.assertEqual(obs, [["2026-06-01", 5.79], ["2026-07-01", 5.81]])

    def test_observacao_sem_valor_e_omitida_nunca_preenchida(self):
        obs = fetch_bcb.normaliza_payload(
            [
                {"data": "01/06/2026", "valor": "5.79"},
                {"data": "01/07/2026", "valor": ""},
            ],
            "x",
        )
        self.assertEqual(obs, [["2026-06-01", 5.79]])

    def test_html_com_status_200_e_recusado(self):
        with self.assertRaises(fetch_bcb.ErroColeta):
            fetch_bcb.normaliza_payload("<html>erro</html>", "x")

    def test_lista_vazia_e_recusada(self):
        with self.assertRaises(fetch_bcb.ErroColeta):
            fetch_bcb.normaliza_payload([], "x")

    def test_payload_sem_nenhum_valor_numerico_e_recusado(self):
        with self.assertRaises(fetch_bcb.ErroColeta):
            fetch_bcb.normaliza_payload([{"data": "01/06/2026", "valor": ""}], "x")


class TestJanelasSgs(unittest.TestCase):
    """O SGS recusa intervalo maior que 10 anos em série diária."""

    def test_todas_as_janelas_tem_menos_de_dez_anos(self):
        for inicio, fim in fetch_bcb._janelas(date(2026, 8, 29)):
            ano_inicio = int(inicio.split("/")[-1])
            ano_fim = int(fim.split("/")[-1])
            self.assertLess(ano_fim - ano_inicio, 10)

    def test_janelas_sao_contiguas_e_cobrem_ate_o_ano_corrente(self):
        janelas = fetch_bcb._janelas(date(2026, 8, 29))
        self.assertEqual(janelas[0][0], f"01/01/{fetch_bcb.ANO_INICIAL}")
        self.assertEqual(janelas[-1][1], "31/12/2026")
        for anterior, seguinte in zip(janelas, janelas[1:]):
            self.assertEqual(int(seguinte[0].split("/")[-1]), int(anterior[1].split("/")[-1]) + 1)


CSV_BIS = (
    "FREQ,BORROWERS_CTY,TIME_PERIOD,OBS_VALUE,TITLE_TS\n"
    "Q,BR,2025-Q4,37.6,Brazil - Credit to Households\n"
    "Q,BR,2025-Q3,,Brazil - Credit to Households\n"
    "Q,BR,2026-Q1,38,Brazil - Credit to Households\n"
)


class TestObservacoesBis(unittest.TestCase):
    def test_valor_vazio_e_descartado_e_ordena_por_data(self):
        obs = fetch_bis.normaliza_observacoes(fetch_bis.le_csv(CSV_BIS, "x"), "x")
        self.assertEqual(obs, [["2025-10-01", 37.6], ["2026-01-01", 38.0]])

    def test_corpo_que_nao_e_o_csv_esperado_e_recusado(self):
        with self.assertRaises(fetch_bcb.ErroColeta):
            fetch_bis.le_csv("<html>erro</html>", "x")
        with self.assertRaises(fetch_bcb.ErroColeta):
            fetch_bis.le_csv("", "x")

    def test_serie_toda_ausente_e_recusada(self):
        linhas = fetch_bis.le_csv("TIME_PERIOD,OBS_VALUE\n2025-Q4,\n", "x")
        with self.assertRaises(fetch_bcb.ErroColeta):
            fetch_bis.normaliza_observacoes(linhas, "x")

    def test_trimestre_vira_primeiro_dia(self):
        self.assertEqual(fetch_bis.parse_periodo_bis("2026-Q1"), date(2026, 1, 1))
        self.assertEqual(fetch_bis.parse_periodo_bis("2025-Q4"), date(2025, 10, 1))


class TestFormatoLongo(unittest.TestCase):
    """Alinhamento de periodicidades diferentes no formato canônico."""

    def setUp(self):
        self.payloads = {
            "mensal": {
                "serie_id": "mensal",
                "fonte": "BCB/SGS",
                "codigo_fonte": "29037",
                "unidade": "%",
                "periodicidade": "M",
                "obs": [["2026-06-01", 49.75], ["2026-05-01", 49.6]],
            },
            "trimestral": {
                "serie_id": "trimestral",
                "fonte": "BIS",
                "codigo_fonte": "Q.BR.H.A.M.770.A",
                "unidade": "% do PIB",
                "periodicidade": "T",
                "obs": [["2025-10-01", 34.2]],
            },
        }

    def test_colunas_na_ordem_canonica(self):
        df = para_formato_longo(self.payloads)
        self.assertEqual(list(df.columns), COLUNAS)

    def test_ordenado_por_serie_e_data(self):
        df = para_formato_longo(self.payloads)
        self.assertEqual(list(df["serie_id"]), ["mensal", "mensal", "trimestral"])
        self.assertEqual([str(d.date()) for d in df["data"]], ["2026-05-01", "2026-06-01", "2025-10-01"])

    def test_periodicidades_convivem_sem_reamostragem(self):
        # Nenhuma linha é criada para alinhar mensal com trimestral.
        df = para_formato_longo(self.payloads)
        self.assertEqual(len(df), 3)

    def test_unidade_preservada_por_serie(self):
        df = para_formato_longo(self.payloads)
        unidades = dict(zip(df["serie_id"], df["unidade"]))
        self.assertEqual(unidades, {"mensal": "%", "trimestral": "% do PIB"})


if __name__ == "__main__":
    unittest.main()
