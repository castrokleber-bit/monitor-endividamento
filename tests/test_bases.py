"""
Testes das cinco bases do seletor "Base de valores". Sem rede.

Cada teste aqui é a tradução de um item do checklist de aceite da orientação de
18/09/2026:

  - deflator: valor real do mês-base igual ao valor nominal do mês-base;
  - variação em 12 meses: primeiros doze meses vazios, sem preenchimento;
  - variação mensal: primeira observação vazia, comparação por calendário;
  - % do PIB: o cálculo próprio reproduz o % do PIB oficial do BCB;
  - nenhuma transformação inventa, interpola ou repete observação.

Uso:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import transformacoes  # noqa: E402


class TestIndiceIpca(unittest.TestCase):
    def test_encadeia_multiplicando(self):
        indice = transformacoes.indice_ipca([["2026-01-01", 1.0], ["2026-02-01", 2.0]])
        self.assertAlmostEqual(indice["2026-01-01"], 1.01)
        self.assertAlmostEqual(indice["2026-02-01"], 1.01 * 1.02)

    def test_variacao_negativa_reduz_o_indice(self):
        indice = transformacoes.indice_ipca([["2026-01-01", 1.0], ["2026-02-01", -0.5]])
        self.assertLess(indice["2026-02-01"], indice["2026-01-01"])

    def test_deflator_vazio_e_recusado(self):
        with self.assertRaises(transformacoes.ErroTransformacao):
            transformacoes.indice_ipca([])


class TestReal(unittest.TestCase):
    def setUp(self):
        self.indice = transformacoes.indice_ipca(
            [["2026-01-01", 1.0], ["2026-02-01", 1.0], ["2026-03-01", 1.0]]
        )
        self.obs = [["2026-01-01", 100.0], ["2026-02-01", 100.0], ["2026-03-01", 100.0]]

    def test_mes_base_fica_com_o_valor_nominal(self):
        """Item do checklist: valor real do mês-base = valor nominal do mês-base."""
        real = dict(transformacoes.real(self.obs, 1, self.indice, "2026-03-01"))
        self.assertAlmostEqual(real["2026-03-01"], 100.0)

    def test_valor_anterior_e_corrigido_pela_inflacao_do_periodo(self):
        real = dict(transformacoes.real(self.obs, 1, self.indice, "2026-03-01"))
        # Dois meses de 1% cada: 100 nominais de janeiro valem 100 x 1,01 x 1,01 em março.
        self.assertAlmostEqual(real["2026-01-01"], 100.0 * 1.01 * 1.01, places=9)

    def test_fator_de_exibicao_e_aplicado(self):
        real = dict(transformacoes.real(self.obs, 0.001, self.indice, "2026-03-01"))
        self.assertAlmostEqual(real["2026-03-01"], 0.1)

    def test_mes_sem_deflator_e_omitido_nunca_preenchido(self):
        obs = self.obs + [["2026-04-01", 100.0]]  # abril não tem IPCA
        real = dict(transformacoes.real(obs, 1, self.indice, "2026-03-01"))
        self.assertNotIn("2026-04-01", real)
        self.assertEqual(len(real), 3)

    def test_base_fora_do_deflator_e_recusada(self):
        with self.assertRaises(transformacoes.ErroTransformacao):
            transformacoes.real(self.obs, 1, self.indice, "2030-01-01")


class TestNominal(unittest.TestCase):
    def test_fator_um_nao_toca_no_valor(self):
        obs = [["2026-01-01", 49.75]]
        self.assertEqual(transformacoes.nominal(obs, 1), obs)

    def test_conversao_de_milhoes_para_bilhoes_sem_ruido_de_ponto_flutuante(self):
        """
        `10284943 * 0.001` dá 10284.943000000001; dividir por 1000 dá 10284.943.

        O rastro de dezessete dígitos ia parar no CSV de download e na planilha. As duas
        contas são matematicamente idênticas — a divisão é a que não introduz erro de
        representação. Não há arredondamento envolvido.
        """
        obs = [["2026-01-01", 10284943.0]]
        self.assertEqual(transformacoes.nominal(obs, 0.001)[0][1], 10284.943)

    def test_fator_que_nao_e_inverso_de_inteiro_continua_multiplicando(self):
        obs = [["2026-01-01", 100.0]]
        self.assertAlmostEqual(transformacoes.nominal(obs, 1.5)[0][1], 150.0)

    def test_divisor_exato_reconhece_potencias_de_dez(self):
        self.assertEqual(transformacoes._divisor_exato(0.001), 1000)
        self.assertEqual(transformacoes._divisor_exato(0.01), 100)
        self.assertIsNone(transformacoes._divisor_exato(1))
        self.assertIsNone(transformacoes._divisor_exato(1.5))


class TestPib(unittest.TestCase):
    def test_razao_em_porcentagem(self):
        obs = [["2026-01-01", 250.0]]
        pib = {"2026-01-01": 1000.0}
        self.assertAlmostEqual(dict(transformacoes.pib(obs, 1, pib))["2026-01-01"], 25.0)

    def test_fator_nao_altera_a_razao(self):
        """
        Numerador e denominador vêm na mesma unidade da fonte, então o fator se cancela.

        O teste existe para travar isso: se alguém aplicar o fator só ao numerador, a
        série passa a marcar 0,025% do PIB onde deveria marcar 25%.
        """
        obs = [["2026-01-01", 250.0]]
        pib = {"2026-01-01": 1000.0}
        com_fator = dict(transformacoes.pib(obs, 0.001, pib))
        sem_fator = dict(transformacoes.pib(obs, 1, pib))
        self.assertEqual(com_fator, sem_fator)

    def test_mes_sem_pib_e_omitido(self):
        obs = [["2026-01-01", 250.0], ["2026-02-01", 260.0]]
        pib = {"2026-01-01": 1000.0}
        self.assertEqual(len(transformacoes.pib(obs, 1, pib)), 1)

    def test_pib_zero_nao_divide(self):
        obs = [["2026-01-01", 250.0]]
        self.assertEqual(transformacoes.pib(obs, 1, {"2026-01-01": 0.0}), [])


class TestVar12m(unittest.TestCase):
    def test_primeiros_doze_meses_ficam_vazios(self):
        """Item do checklist: os doze primeiros meses saem da série, sem preenchimento."""
        obs = [[f"2025-{m:02d}-01", 100.0] for m in range(1, 13)]
        obs += [[f"2026-{m:02d}-01", 110.0] for m in range(1, 13)]
        saida = transformacoes.var12m(obs)
        self.assertEqual(len(saida), 12)
        self.assertEqual(saida[0][0], "2026-01-01")

    def test_variacao_percentual(self):
        obs = [["2025-01-01", 100.0], ["2026-01-01", 110.0]]
        self.assertAlmostEqual(dict(transformacoes.var12m(obs))["2026-01-01"], 10.0)

    def test_independe_do_fator(self):
        # Igualdade aproximada, não exata: multiplicar os dois termos por 0,001 antes de
        # dividir muda o último bit do float. A garantia que interessa é a de que a
        # conversão de unidade não desloca a variação, e não a de bit idêntico.
        obs = [["2025-01-01", 100.0], ["2026-01-01", 110.0]]
        escalada = [[d, v * 0.001] for d, v in obs]
        self.assertAlmostEqual(
            transformacoes.var12m(obs)[0][1],
            transformacoes.var12m(escalada)[0][1],
            places=9,
        )

    def test_compara_por_calendario_e_nao_por_posicao(self):
        """
        Série com buraco não pode comparar com o décimo segundo ponto anterior.

        Aqui falta 2025-06. Se a comparação fosse por posição na lista, 2026-06 acabaria
        comparado com 2025-05 e a variação sairia errada em silêncio.
        """
        obs = [[f"2025-{m:02d}-01", 100.0] for m in range(1, 13) if m != 6]
        obs += [[f"2026-{m:02d}-01", 110.0] for m in range(1, 13)]
        saida = dict(transformacoes.var12m(obs))
        self.assertNotIn("2026-06-01", saida)
        self.assertIn("2026-05-01", saida)
        self.assertIn("2026-07-01", saida)

    def test_valor_anterior_zero_e_omitido(self):
        obs = [["2025-01-01", 0.0], ["2026-01-01", 110.0]]
        self.assertEqual(transformacoes.var12m(obs), [])


class TestVar1m(unittest.TestCase):
    def test_variacao_contra_o_mes_anterior(self):
        obs = [["2026-01-01", 100.0], ["2026-02-01", 110.0]]
        self.assertAlmostEqual(dict(transformacoes.var1m(obs))["2026-02-01"], 10.0)

    def test_primeira_observacao_fica_vazia(self):
        obs = [[f"2026-{m:02d}-01", 100.0] for m in range(1, 7)]
        saida = transformacoes.var1m(obs)
        self.assertEqual(len(saida), 5)
        self.assertEqual(saida[0][0], "2026-02-01")

    def test_atravessa_a_virada_do_ano(self):
        obs = [["2025-12-01", 100.0], ["2026-01-01", 105.0]]
        self.assertAlmostEqual(dict(transformacoes.var1m(obs))["2026-01-01"], 5.0)

    def test_independe_do_fator(self):
        obs = [["2026-01-01", 100.0], ["2026-02-01", 110.0]]
        escalada = [[d, v * 0.001] for d, v in obs]
        self.assertAlmostEqual(
            transformacoes.var1m(obs)[0][1], transformacoes.var1m(escalada)[0][1], places=9
        )

    def test_compara_por_calendario_e_nao_por_posicao(self):
        """
        Série com buraco não pode comparar com o ponto anterior da lista.

        Aqui falta 2026-03. Se a comparação fosse por posição, 2026-04 acabaria comparado
        com 2026-02 — uma variação de dois meses apresentada como mensal.
        """
        obs = [["2026-01-01", 100.0], ["2026-02-01", 110.0], ["2026-04-01", 120.0]]
        saida = dict(transformacoes.var1m(obs))
        self.assertIn("2026-02-01", saida)
        self.assertNotIn("2026-04-01", saida)

    def test_valor_anterior_zero_e_omitido(self):
        obs = [["2026-01-01", 0.0], ["2026-02-01", 110.0]]
        self.assertEqual(transformacoes.var1m(obs), [])

    def test_nao_se_confunde_com_var12m(self):
        """Doze meses de valores diferentes: as duas bases têm de discordar."""
        obs = [[f"2025-{m:02d}-01", 100.0 + m] for m in range(1, 13)]
        obs += [["2026-01-01", 200.0]]
        self.assertNotAlmostEqual(
            dict(transformacoes.var1m(obs))["2026-01-01"],
            dict(transformacoes.var12m(obs))["2026-01-01"],
        )


class TestMesAnterior(unittest.TestCase):
    def test_subtrai_um_mes(self):
        self.assertEqual(transformacoes.mes_anterior("2026-07-01"), "2026-06-01")

    def test_janeiro_volta_para_dezembro_do_ano_anterior(self):
        self.assertEqual(transformacoes.mes_anterior("2026-01-01"), "2025-12-01")

    def test_preserva_o_zero_a_esquerda(self):
        self.assertEqual(transformacoes.mes_anterior("2026-10-01"), "2026-09-01")


class TestDozeMesesAntes(unittest.TestCase):
    def test_subtrai_um_ano(self):
        self.assertEqual(transformacoes.doze_meses_antes("2026-07-01"), "2025-07-01")

    def test_virada_de_seculo(self):
        self.assertEqual(transformacoes.doze_meses_antes("2000-01-01"), "1999-01-01")


class TestMarcadorDeUnidade(unittest.TestCase):
    def test_substitui_pelo_mes_base(self):
        self.assertEqual(
            transformacoes.aplica_marcador("R$ bilhões de {base_ipca}", "2026-08-01"),
            "R$ bilhões de ago/2026",
        )

    def test_texto_sem_marcador_passa_intacto(self):
        self.assertEqual(transformacoes.aplica_marcador("% do PIB", "2026-08-01"), "% do PIB")

    def test_sem_base_nao_inventa_mes(self):
        self.assertIn(
            "indisponível", transformacoes.aplica_marcador("R$ de {base_ipca}", None)
        )


class TestContrato(unittest.TestCase):
    """
    O catálogo e o motor têm de concordar sobre quais bases existem.

    Uma base nova declarada num YAML sem implementação correspondente produziria um
    seletor com uma opção que não desenha nada. Este teste pega isso no CI.
    """

    def test_bases_do_catalogo_sao_implementadas(self):
        import yaml

        raiz = Path(__file__).resolve().parent.parent
        abas = yaml.safe_load((raiz / "config" / "abas.yaml").read_text(encoding="utf-8"))
        declaradas = {b["id"] for b in abas["bases"]}
        self.assertEqual(declaradas, set(transformacoes.BASES))

    def test_base_desconhecida_e_recusada(self):
        with self.assertRaises(transformacoes.ErroTransformacao):
            transformacoes.aplica("inventada", [["2026-01-01", 1.0]], {}, None)


if __name__ == "__main__":
    unittest.main()
