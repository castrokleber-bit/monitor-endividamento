"""
Testes do deflacionamento — a única operação de cálculo do monitor. Sem rede.

O que estes testes protegem: o índice encadeado, a escolha do mês-base, a omissão (nunca
o preenchimento) de mês sem deflator e a unidade que declara a base.

Uso:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import derivadas  # noqa: E402


def _payload(serie_id: str, obs: list[list], unidade: str, codigo: str) -> dict:
    return {
        "serie_id": serie_id,
        "fonte": "BCB/SGS",
        "codigo_fonte": codigo,
        "unidade": unidade,
        "periodicidade": "M",
        "coletado_em": "2026-08-30T00:00:00+00:00",
        "obs": obs,
    }


# IPCA de brinquedo: 10% no primeiro mês, 0% no segundo, 10% no terceiro.
IPCA = [["2026-01-01", 10.0], ["2026-02-01", 0.0], ["2026-03-01", 10.0]]


class TestIndiceEncadeado(unittest.TestCase):
    def test_encadeia_multiplicando(self):
        indice = derivadas.indice_encadeado(IPCA)
        self.assertAlmostEqual(indice["2026-01-01"], 1.10)
        self.assertAlmostEqual(indice["2026-02-01"], 1.10)
        self.assertAlmostEqual(indice["2026-03-01"], 1.21)

    def test_variacao_negativa_reduz_o_indice(self):
        indice = derivadas.indice_encadeado([["2026-01-01", 10.0], ["2026-02-01", -10.0]])
        self.assertAlmostEqual(indice["2026-02-01"], 1.10 * 0.9)

    def test_deflator_vazio_e_recusado(self):
        with self.assertRaises(derivadas.ErroDerivada):
            derivadas.indice_encadeado([])


class TestDeflaciona(unittest.TestCase):
    def setUp(self):
        self.indice = derivadas.indice_encadeado(IPCA)

    def test_mes_base_fica_com_o_valor_nominal(self):
        obs = derivadas.deflaciona([["2026-03-01", 100.0]], self.indice, "2026-03-01")
        self.assertAlmostEqual(obs[0][1], 100.0)

    def test_valor_anterior_e_corrigido_pela_inflacao_do_periodo(self):
        # De janeiro a março o índice sobe 10% (1,10 -> 1,21).
        obs = derivadas.deflaciona([["2026-01-01", 100.0]], self.indice, "2026-03-01")
        self.assertAlmostEqual(obs[0][1], 110.0)

    def test_mes_sem_deflator_e_omitido_nunca_preenchido(self):
        nominal = [["2026-03-01", 100.0], ["2026-04-01", 100.0]]
        obs = derivadas.deflaciona(nominal, self.indice, "2026-03-01")
        self.assertEqual([o[0] for o in obs], ["2026-03-01"])

    def test_base_fora_do_deflator_e_recusada(self):
        with self.assertRaises(derivadas.ErroDerivada):
            derivadas.deflaciona([["2026-01-01", 100.0]], self.indice, "2026-09-01")


class TestConstroi(unittest.TestCase):
    def setUp(self):
        self.config = {
            "deflacionamento": {"deflator": "ipca", "base": "ultima_do_deflator"},
            "series": [
                {
                    "serie_id": "saldo_real",
                    "origem": "saldo",
                    "operacao": "deflaciona_ipca",
                    "rotulo": "Total",
                }
            ],
        }
        self.payloads = {
            "ipca": _payload("ipca", list(IPCA), "% ao mês", "433"),
            "saldo": _payload(
                "saldo",
                [["2026-01-01", 100.0], ["2026-03-01", 200.0]],
                "R$ milhões",
                "20539",
            ),
        }

    def test_base_e_a_ultima_observacao_do_deflator(self):
        _, _, base = derivadas.constroi(self.config, self.payloads, {})
        self.assertEqual(base, "2026-03-01")

    def test_unidade_declara_o_mes_base(self):
        novos, entradas, _ = derivadas.constroi(self.config, self.payloads, {})
        self.assertEqual(novos["saldo_real"]["unidade"], "R$ milhões de mar/2026")
        self.assertEqual(entradas["saldo_real"]["unidade"], "R$ milhões de mar/2026")

    def test_procedencia_cita_origem_e_deflator(self):
        _, entradas, _ = derivadas.constroi(self.config, self.payloads, {})
        calculo = entradas["saldo_real"]["calculo"]
        self.assertIn("20539", calculo)
        self.assertIn("433", calculo)

    def test_sem_deflator_nao_deriva_nada(self):
        del self.payloads["ipca"]
        novos, entradas, base = derivadas.constroi(self.config, self.payloads, {})
        self.assertEqual((novos, entradas, base), ({}, {}, None))

    def test_origem_ausente_apenas_nao_gera_a_derivada(self):
        del self.payloads["saldo"]
        novos, _, base = derivadas.constroi(self.config, self.payloads, {})
        self.assertEqual(novos, {})
        self.assertEqual(base, "2026-03-01")

    def test_operacao_desconhecida_falha(self):
        self.config["series"][0]["operacao"] = "inventada"
        with self.assertRaises(derivadas.ErroDerivada):
            derivadas.constroi(self.config, self.payloads, {})


class TestMarcadorDeUnidade(unittest.TestCase):
    def test_substitui_pelo_mes_base(self):
        self.assertEqual(
            derivadas.aplica_marcador("R$ milhões de {base_ipca}", "2026-07-01"),
            "R$ milhões de jul/2026",
        )

    def test_texto_sem_marcador_passa_intacto(self):
        self.assertEqual(derivadas.aplica_marcador("% do PIB", "2026-07-01"), "% do PIB")

    def test_sem_base_nao_inventa_mes(self):
        saida = derivadas.aplica_marcador("R$ milhões de {base_ipca}", None)
        self.assertNotIn("{base_ipca}", saida)
        self.assertIn("indisponível", saida)


class TestCatalogoDerivadas(unittest.TestCase):
    """O YAML real precisa casar com o que o código sabe executar."""

    def test_toda_serie_declara_operacao_conhecida_e_origem_do_catalogo(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from build_dataset import catalogo_completo  # noqa: PLC0415
        from comum import carrega_catalogo  # noqa: PLC0415

        config = carrega_catalogo("derivadas.yaml")
        catalogo = catalogo_completo()

        self.assertIn(config["deflacionamento"]["deflator"], catalogo)
        for serie in config["series"]:
            self.assertEqual(serie["operacao"], "deflaciona_ipca")
            self.assertIn(serie["origem"], catalogo)


if __name__ == "__main__":
    unittest.main()
