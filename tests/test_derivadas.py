"""
Testes das séries derivadas — residual, soma e média ponderada. Sem rede.

O que estes testes protegem, em ordem de importância:

  - o residual FECHA: total = soma das parcelas exibidas + residual, em todas as datas.
    É o item mais duro do checklist de aceite, e é a razão de a parcela "Outros" dos
    gráficos de saldo ser calculada em vez de coletada;
  - a média ponderada agrega taxa do jeito certo, ponderando pelo saldo, e não pela
    média simples;
  - data em que falta um insumo não entra no resultado — nada é interpolado ou repetido;
  - o catálogo em config/derivadas.yaml não referencia série que não existe.

Uso:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import derivadas  # noqa: E402


def _payload(serie_id: str, obs: list[list], unidade: str = "R$ milhões", codigo: str = "1") -> dict:
    return {
        "serie_id": serie_id,
        "fonte": "BCB/SGS",
        "codigo_fonte": codigo,
        "unidade": unidade,
        "periodicidade": "M",
        "coletado_em": "2026-09-19T00:00:00+00:00",
        "obs": obs,
    }


class TestResidual(unittest.TestCase):
    def test_total_menos_componentes(self):
        total = [["2026-01-01", 100.0], ["2026-02-01", 110.0]]
        a = [["2026-01-01", 30.0], ["2026-02-01", 35.0]]
        b = [["2026-01-01", 20.0], ["2026-02-01", 25.0]]
        self.assertEqual(
            derivadas.residual(total, [a, b]),
            [["2026-01-01", 50.0], ["2026-02-01", 50.0]],
        )

    def test_fecha_exatamente(self):
        """A soma das parcelas exibidas mais o residual reproduz o total publicado."""
        total = [["2026-01-01", 1590492.0]]
        partes = [[["2026-01-01", v]] for v in (382840.0, 92537.0, 176069.0, 133936.0)]
        resto = derivadas.residual(total, partes)
        soma = sum(p[0][1] for p in partes) + resto[0][1]
        self.assertAlmostEqual(soma, total[0][1], places=6)

    def test_data_sem_componente_fica_de_fora(self):
        total = [["2026-01-01", 100.0], ["2026-02-01", 110.0]]
        a = [["2026-01-01", 30.0]]
        self.assertEqual(derivadas.residual(total, [a]), [["2026-01-01", 70.0]])

    def test_residual_pode_ser_negativo_e_nao_e_zerado(self):
        """
        Componentes que somam mais que o total produzem residual negativo.

        Não é para acontecer, mas se acontecer o número tem de aparecer como está: zerar
        em silêncio esconderia um erro de catálogo — uma série no gráfico errado, por
        exemplo — que o leitor veria como composição que não fecha.
        """
        total = [["2026-01-01", 100.0]]
        a = [["2026-01-01", 130.0]]
        self.assertEqual(derivadas.residual(total, [a]), [["2026-01-01", -30.0]])


class TestSoma(unittest.TestCase):
    def test_soma_componentes(self):
        a = [["2026-01-01", 1324220.0]]
        b = [["2026-01-01", 1417828.0]]
        self.assertEqual(derivadas.soma([a, b]), [["2026-01-01", 2742048.0]])

    def test_so_datas_comuns(self):
        a = [["2026-01-01", 1.0], ["2026-02-01", 2.0]]
        b = [["2026-02-01", 3.0]]
        self.assertEqual(derivadas.soma([a, b]), [["2026-02-01", 5.0]])


class TestMediaPonderada(unittest.TestCase):
    def test_pondera_pelo_peso_e_nao_pela_media_simples(self):
        taxa_a = [["2026-01-01", 6.0]]
        peso_a = [["2026-01-01", 1324220.0]]
        taxa_b = [["2026-01-01", 0.8]]
        peso_b = [["2026-01-01", 1417828.0]]
        resultado = derivadas.media_ponderada([(taxa_a, peso_a), (taxa_b, peso_b)])[0][1]
        esperado = (6.0 * 1324220.0 + 0.8 * 1417828.0) / (1324220.0 + 1417828.0)
        self.assertAlmostEqual(resultado, esperado)
        self.assertNotAlmostEqual(resultado, (6.0 + 0.8) / 2)

    def test_reproduz_um_total_oficial_conhecido(self):
        """
        Caso real, conferido contra a API em 19/09/2026, observação de 07/2026.

        Ponderando a inadimplência de pessoas jurídicas (21083 = 3,31%) e de pessoas
        físicas (21084 = 5,81%) pelos saldos correspondentes (20540 e 20541), o resultado
        tem de reproduzir o total oficial do SFN (21082 = 4,88%). É a prova de que a
        fórmula usada para construir o total por porte — que a fonte não publica — é a
        mesma que o Banco Central usa onde ele publica.
        """
        pj = ([["2026-07-01", 3.31]], [["2026-07-01", 2731513.0]])
        pf = ([["2026-07-01", 5.81]], [["2026-07-01", 4640730.0]])
        resultado = derivadas.media_ponderada([pj, pf])[0][1]
        self.assertAlmostEqual(resultado, 4.88, places=2)

    def test_peso_total_zero_fica_de_fora(self):
        taxa = [["2026-01-01", 5.0]]
        peso = [["2026-01-01", 0.0]]
        self.assertEqual(derivadas.media_ponderada([(taxa, peso)]), [])


class TestConstroi(unittest.TestCase):
    def setUp(self):
        self.config = {
            "fonte": "Derivado",
            "series": [
                {
                    "serie_id": "resto",
                    "operacao": "residual",
                    "total": "t",
                    "componentes": ["a"],
                    "rotulo": "Outras",
                    "unidade": "R$ milhões",
                    "fator": 0.001,
                    "unidade_exibicao": "R$ bilhões",
                    "segmento": "empresa",
                    "bases": ["nominal"],
                }
            ],
        }
        self.payloads = {
            "t": _payload("t", [["2026-01-01", 100.0]], codigo="20543"),
            "a": _payload("a", [["2026-01-01", 30.0]], codigo="20547"),
        }

    def test_produz_a_serie_e_a_entrada_de_catalogo(self):
        novos, entradas = derivadas.constroi(self.config, self.payloads, {})
        self.assertEqual(novos["resto"]["obs"], [["2026-01-01", 70.0]])
        self.assertIn("20543", entradas["resto"]["calculo"])
        self.assertIn("20547", entradas["resto"]["calculo"])

    def test_insumo_ausente_apenas_nao_gera_a_derivada(self):
        """Fonte fora do ar não pode derrubar o build: a derivada some, o resto segue."""
        del self.payloads["a"]
        novos, _ = derivadas.constroi(self.config, self.payloads, {})
        self.assertEqual(novos, {})

    def test_operacao_desconhecida_e_recusada(self):
        self.config["series"][0]["operacao"] = "inventada"
        with self.assertRaises(derivadas.ErroDerivada):
            derivadas.constroi(self.config, self.payloads, {})

    def test_confere_fechamento_aprova_o_residual_correto(self):
        novos, _ = derivadas.constroi(self.config, self.payloads, {})
        self.payloads.update(novos)
        self.assertEqual(derivadas.confere_fechamento(self.config, self.payloads), [])

    def test_confere_fechamento_pega_residual_adulterado(self):
        novos, _ = derivadas.constroi(self.config, self.payloads, {})
        novos["resto"]["obs"] = [["2026-01-01", 69.0]]
        self.payloads.update(novos)
        self.assertTrue(derivadas.confere_fechamento(self.config, self.payloads))


class TestCatalogoReal(unittest.TestCase):
    """O YAML de produção precisa ser coerente com os catálogos de coleta."""

    @classmethod
    def setUpClass(cls):
        cls.derivadas = yaml.safe_load(
            (RAIZ / "config" / "derivadas.yaml").read_text(encoding="utf-8")
        )
        cls.coletadas = set()
        for arquivo in ("series_bcb.yaml", "series_fred.yaml"):
            cat = yaml.safe_load((RAIZ / "config" / arquivo).read_text(encoding="utf-8"))
            cls.coletadas.update(s["serie_id"] for s in cat["series"])

    def test_toda_operacao_e_conhecida(self):
        for serie in self.derivadas["series"]:
            self.assertIn(serie["operacao"], derivadas.OPERACOES, serie["serie_id"])

    def test_todo_insumo_existe_no_catalogo_de_coleta(self):
        for serie in self.derivadas["series"]:
            for insumo in derivadas._insumos(serie):
                self.assertIn(
                    insumo,
                    self.coletadas,
                    f"{serie['serie_id']} depende de {insumo}, que não é coletada",
                )

    def test_toda_derivada_declara_unidade_segmento_e_bases(self):
        for serie in self.derivadas["series"]:
            for campo in ("unidade", "unidade_exibicao", "segmento", "bases", "rotulo"):
                self.assertIn(campo, serie, f"{serie['serie_id']} sem {campo}")

    def test_nenhuma_derivada_colide_com_serie_coletada(self):
        for serie in self.derivadas["series"]:
            self.assertNotIn(serie["serie_id"], self.coletadas)


if __name__ == "__main__":
    unittest.main()
