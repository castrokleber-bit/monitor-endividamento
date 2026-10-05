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
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb")

        self.assertEqual(entrada["status"], "ok")
        self.assertEqual(entrada["n_obs"], 2)
        self.assertEqual(entrada["ultima_data"], "2026-06-01")
        self.assertEqual(payload["obs"], PAYLOAD_BOM["obs"])
        self.assertTrue(comum.caminho_cache("serie_teste").exists())

    def test_falha_com_cache_reusa_e_marca_stale(self):
        comum.grava_cache("serie_teste", PAYLOAD_BOM)

        with mock.patch.object(fetch_bcb, "coleta", side_effect=fetch_bcb.ErroColeta("503")):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb")

        self.assertEqual(entrada["status"], "stale")
        self.assertIn("503", entrada["motivo"])
        self.assertEqual(payload["obs"], PAYLOAD_BOM["obs"])

    def test_stale_registra_a_data_do_ultimo_dado_bom(self):
        comum.grava_cache("serie_teste", PAYLOAD_BOM)

        with mock.patch.object(fetch_bcb, "coleta", side_effect=fetch_bcb.ErroColeta("503")):
            _, entrada = build_dataset.coleta_serie(SERIE, "bcb")

        self.assertEqual(entrada["ultima_coleta_ok"], PAYLOAD_BOM["coletado_em"])

    def test_falha_sem_cache_marca_ausente_e_nao_levanta(self):
        with mock.patch.object(fetch_bcb, "coleta", side_effect=fetch_bcb.ErroColeta("406")):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb")

        self.assertIsNone(payload)
        self.assertEqual(entrada["status"], "ausente")
        self.assertEqual(entrada["n_obs"], 0)
        self.assertIsNone(entrada["ultima_coleta_ok"])

    def test_falha_de_rede_tambem_cai_para_o_cache(self):
        # `comum.http_get` levanta RuntimeError depois de esgotar os retries.
        comum.grava_cache("serie_teste", PAYLOAD_BOM)

        with mock.patch.object(fetch_bcb, "coleta", side_effect=RuntimeError("falha de rede")):
            _, entrada = build_dataset.coleta_serie(SERIE, "bcb")

        self.assertEqual(entrada["status"], "stale")

    def test_cache_corrompido_nao_derruba_e_vira_ausente(self):
        comum.caminho_cache("serie_teste").write_text("{ nao é json", encoding="utf-8")

        with mock.patch.object(fetch_bcb, "coleta", side_effect=fetch_bcb.ErroColeta("503")):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb")

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



class TestCacheDeOutroCodigo(unittest.TestCase):
    """
    Cache gravado com um código não pode amparar a série depois que o código mudou.

    O cache é indexado por `serie_id`. Corrigido um código errado no YAML, o arquivo antigo
    continua lá — e, numa queda da fonte, publicaria o dado do código velho sob o novo.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patch = mock.patch.object(comum, "CACHE", self.tmp)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        comum.grava_cache("serie_teste", dict(PAYLOAD_BOM, codigo_fonte="99999"))

    def test_falha_com_cache_de_outro_codigo_vira_ausente(self):
        with mock.patch.object(fetch_bcb, "coleta", side_effect=fetch_bcb.ErroColeta("503")):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb")
        self.assertIsNone(payload)
        self.assertEqual(entrada["status"], "ausente")
        self.assertIn("99999", entrada["motivo"])
        self.assertIn("12345", entrada["motivo"])

    def test_do_cache_tambem_recusa(self):
        payload, entrada = build_dataset.do_cache(SERIE, "bcb")
        self.assertIsNone(payload)
        self.assertEqual(entrada["status"], "ausente")
        self.assertIn("cache descartado", entrada["motivo"])

    def test_cache_do_mesmo_codigo_continua_servindo(self):
        comum.grava_cache("serie_teste", PAYLOAD_BOM)
        payload, entrada = build_dataset.do_cache(SERIE, "bcb")
        self.assertEqual(entrada["status"], "ok")
        self.assertEqual(payload["obs"], PAYLOAD_BOM["obs"])


class TestRedeDeProtecaoDaColeta(unittest.TestCase):
    """Qualquer exceção numa série vira `stale`/`ausente` daquela série, com o tipo no motivo."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patch = mock.patch.object(comum, "CACHE", self.tmp)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_excecao_inesperada_nao_derruba_e_registra_o_tipo(self):
        comum.grava_cache("serie_teste", PAYLOAD_BOM)
        with mock.patch.object(fetch_bcb, "coleta", side_effect=TypeError("payload estranho")):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb")
        self.assertEqual(entrada["status"], "stale")
        self.assertTrue(entrada["motivo"].startswith("TypeError:"))
        self.assertEqual(payload["obs"], PAYLOAD_BOM["obs"])

    def test_excecao_inesperada_sem_cache_vira_ausente(self):
        with mock.patch.object(fetch_bcb, "coleta", side_effect=AttributeError("x")):
            payload, entrada = build_dataset.coleta_serie(SERIE, "bcb")
        self.assertIsNone(payload)
        self.assertEqual(entrada["status"], "ausente")
        self.assertIn("AttributeError", entrada["motivo"])


def _catalogo_falso(n_bcb: int, n_bis: int = 1):
    """Dublê de `carrega_catalogo` com `n` séries por fonte, sem tocar em config/."""

    def carrega(arquivo):
        if arquivo == build_dataset.CATALOGOS["bcb"]:
            series = [dict(SERIE, serie_id=f"b{i}", codigo=1000 + i) for i in range(n_bcb)]
            return {"fonte": "BCB/SGS", "series": series}
        series = [dict(SERIE, serie_id=f"i{i}", codigo=f"Q.X.{i}") for i in range(n_bis)]
        return {"fonte": "BIS", "series": series}

    return carrega


def _payload_de(serie: dict) -> dict:
    return dict(PAYLOAD_BOM, serie_id=serie["serie_id"], codigo_fonte=str(serie["codigo"]))


class TestDisjuntorDaColeta(unittest.TestCase):
    """
    Fonte que cai no meio da execução: depois de N falhas de rede seguidas, o resto da
    fonte vem do cache sem nova tentativa. Código errado não conta para o disjuntor.
    """

    N = build_dataset.LIMITE_FALHAS_SEGUIDAS

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        mock.patch.object(comum, "CACHE", self.tmp).start()
        mock.patch.object(build_dataset.time, "sleep").start()
        mock.patch.object(build_dataset, "carrega_catalogo", _catalogo_falso(self.N + 4)).start()
        self.bis = mock.patch.object(
            build_dataset.fetch_bis, "coleta", side_effect=_payload_de
        ).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for i in range(self.N + 4):
            comum.grava_cache(f"b{i}", _payload_de({"serie_id": f"b{i}", "codigo": 1000 + i}))

    def test_abre_depois_de_n_falhas_de_rede_seguidas(self):
        rede = comum.ErroDeRede("falha de rede em url: HTTP 503 após 4 tentativas")
        with mock.patch.object(fetch_bcb, "coleta", side_effect=rede) as coleta:
            payloads, manifesto, _ = build_dataset.coleta_tudo(["bcb", "bis"])

        self.assertEqual(coleta.call_count, self.N)  # as quatro restantes nem tentaram
        bcb = [m for m in manifesto if m["serie_id"].startswith("b")]
        self.assertTrue(all(m["status"] == "stale" for m in bcb))
        abertas = [m for m in bcb if "disjuntor" in (m["motivo"] or "")]
        self.assertEqual(len(abertas), 4)
        self.assertEqual(len(payloads), self.N + 4 + 1)
        # o disjuntor é por fonte: o BIS foi coletado normalmente
        self.assertEqual(self.bis.call_count, 1)

    def test_estrangulamento_persistente_tambem_conta(self):
        falha = fetch_bcb.FonteIndisponivel("HTTP 400 em consulta sem intervalo")
        with mock.patch.object(fetch_bcb, "coleta", side_effect=falha) as coleta:
            build_dataset.coleta_tudo(["bcb"])
        self.assertEqual(coleta.call_count, self.N)

    def test_codigo_inexistente_nao_conta(self):
        falha = fetch_bcb.CodigoInexistente("406 — código inexistente")
        with mock.patch.object(fetch_bcb, "coleta", side_effect=falha) as coleta:
            build_dataset.coleta_tudo(["bcb"])
        self.assertEqual(coleta.call_count, self.N + 4)

    def test_sucesso_no_meio_zera_a_contagem(self):
        rede = comum.ErroDeRede("falha de rede")
        efeitos = [rede] * (self.N - 1) + [_payload_de({"serie_id": "b4", "codigo": 1004})]
        efeitos += [rede] * 4
        with mock.patch.object(fetch_bcb, "coleta", side_effect=efeitos) as coleta:
            build_dataset.coleta_tudo(["bcb"])
        self.assertEqual(coleta.call_count, self.N + 4)


class TestExecucaoParcial(unittest.TestCase):
    """`--fonte bcb` não pode produzir artefato sem o BIS: a fonte de fora vem do cache."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        mock.patch.object(comum, "CACHE", self.tmp).start()
        mock.patch.object(build_dataset.time, "sleep").start()
        mock.patch.object(build_dataset, "carrega_catalogo", _catalogo_falso(2, 2)).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_fonte_fora_do_recorte_vem_do_cache_sem_rede(self):
        comum.grava_cache("i0", _payload_de({"serie_id": "i0", "codigo": "Q.X.0"}))
        with mock.patch.object(fetch_bcb, "coleta", side_effect=_payload_de), mock.patch.object(
            build_dataset.fetch_bis, "coleta"
        ) as bis:
            payloads, manifesto, catalogo = build_dataset.coleta_tudo(["bcb"])

        bis.assert_not_called()
        status = {m["serie_id"]: m["status"] for m in manifesto}
        self.assertEqual(status, {"b0": "ok", "b1": "ok", "i0": "ok", "i1": "ausente"})
        self.assertIn("fora do recorte", next(m for m in manifesto if m["serie_id"] == "i0")["motivo"])
        self.assertEqual(set(catalogo), {"b0", "b1", "i0", "i1"})
        self.assertIn("i0", payloads)

    def test_serie_sem_cache_da_fonte_de_fora_aciona_o_guard(self):
        with mock.patch.object(fetch_bcb, "coleta", side_effect=_payload_de):
            _, manifesto, _ = build_dataset.coleta_tudo(["bcb"])
        anterior = [{"serie_id": "i1", "status": "ok", "n_obs": 2}]
        bloqueios, _ = build_dataset.verifica_regressao(manifesto, anterior)
        self.assertTrue(any("i1" in b for b in bloqueios))


class TestStatusDasDerivadas(unittest.TestCase):
    """Uma derivada herda o pior status dos insumos e a coleta boa mais antiga."""

    CONFIG = {
        "fonte": "Derivado",
        "series": [
            {
                "serie_id": "resto",
                "operacao": "residual",
                "total": "t",
                "componentes": ["a"],
                "unidade": "R$ milhões",
            }
        ],
    }

    def _roda(self, status_a: str):
        payloads = {
            "t": dict(PAYLOAD_BOM, serie_id="t", coletado_em="2026-10-04T00:00:00+00:00",
                      obs=[["2026-06-01", 100.0]]),
            "a": dict(PAYLOAD_BOM, serie_id="a", coletado_em="2026-09-01T00:00:00+00:00",
                      obs=[["2026-06-01", 30.0]]),
        }
        manifesto = [
            {"serie_id": "t", "status": "ok", "ultima_coleta_ok": "2026-10-04T00:00:00+00:00"},
            {"serie_id": "a", "status": status_a, "ultima_coleta_ok": "2026-09-01T00:00:00+00:00"},
        ]
        with mock.patch.object(build_dataset, "carrega_catalogo", return_value=self.CONFIG):
            build_dataset.deriva_tudo(payloads, {}, manifesto)
        return next(m for m in manifesto if m["serie_id"] == "resto")

    def test_insumo_stale_deixa_a_derivada_stale(self):
        entrada = self._roda("stale")
        self.assertEqual(entrada["status"], "stale")
        self.assertIn("a", entrada["motivo"])

    def test_todos_ok_deixa_ok(self):
        self.assertEqual(self._roda("ok")["status"], "ok")

    def test_ultima_coleta_ok_e_a_do_insumo_mais_antigo(self):
        entrada = self._roda("ok")
        self.assertEqual(entrada["ultima_coleta_ok"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(entrada["coletado_em"], "2026-09-01T00:00:00+00:00")


class TestIdentidadesContabeis(unittest.TestCase):
    """`total = soma(parcelas)` dentro da tolerância — o teste mais forte do catálogo."""

    IDENT = [{"id": "x", "total": "t", "parcelas": ["a", "b"], "tolerancia": 10}]

    @staticmethod
    def _p(sid, *valores):
        obs = [[f"2026-0{i + 1}-01", v] for i, v in enumerate(valores)]
        return dict(PAYLOAD_BOM, serie_id=sid, obs=obs)

    def _manifesto(self, **status):
        return [{"serie_id": s, "status": status.get(s, "ok")} for s in ("t", "a", "b")]

    def test_fecha_com_arredondamento_da_fonte(self):
        payloads = {
            "t": self._p("t", 100.0, 202.0),
            "a": self._p("a", 60.0, 100.0),
            "b": self._p("b", 40.0, 100.0),
        }
        problemas, avisos = build_dataset.confere_identidades(self.IDENT, payloads, self._manifesto())
        self.assertEqual((problemas, avisos), ([], []))

    def test_codigo_trocado_nao_fecha_e_reprova(self):
        payloads = {
            "t": self._p("t", 100.0, 200.0),
            "a": self._p("a", 60.0, 100.0),
            "b": self._p("b", 40.0, 5000.0),  # outra série no lugar da parcela
        }
        problemas, _ = build_dataset.confere_identidades(self.IDENT, payloads, self._manifesto())
        self.assertEqual(len(problemas), 1)
        self.assertIn("2026-02-01", problemas[0])

    def test_membro_stale_nao_e_conferido_e_avisa(self):
        payloads = {
            "t": self._p("t", 100.0),
            "a": self._p("a", 60.0),
            "b": self._p("b", 900.0),
        }
        problemas, avisos = build_dataset.confere_identidades(
            self.IDENT, payloads, self._manifesto(b="stale")
        )
        self.assertEqual(problemas, [])
        self.assertTrue(any("desatualizada" in a for a in avisos))

    def test_membro_ausente_avisa(self):
        payloads = {"t": self._p("t", 100.0), "a": self._p("a", 60.0)}
        problemas, avisos = build_dataset.confere_identidades(self.IDENT, payloads, self._manifesto())
        self.assertEqual(problemas, [])
        self.assertTrue(any("ausente" in a for a in avisos))

    def test_config_aponta_serie_inexistente_e_tolerancia_invalida(self):
        catalogo = {s: {"unidade": "R$ milhões"} for s in ("t", "a")}
        ident = [{"id": "x", "total": "t", "parcelas": ["a", "zz"], "tolerancia": 10},
                 {"id": "y", "total": "t", "parcelas": ["a", "a"], "tolerancia": -1}]
        problemas = build_dataset.confere_identidades_config(catalogo, ident)
        self.assertTrue(any("zz" in p for p in problemas))
        self.assertTrue(any("tolerancia" in p for p in problemas))

    def test_config_recusa_unidades_misturadas(self):
        catalogo = {"t": {"unidade": "R$ milhões"}, "a": {"unidade": "%"}, "b": {"unidade": "%"}}
        problemas = build_dataset.confere_identidades_config(catalogo, self.IDENT)
        self.assertTrue(any("unidades" in p for p in problemas))

    def test_identidades_de_producao_estao_coerentes_com_o_catalogo(self):
        problemas = build_dataset.confere_identidades_config(
            build_dataset.catalogo_completo(), build_dataset.carrega_identidades()
        )
        self.assertEqual(problemas, [], "\n".join(problemas))

    def test_as_identidades_pedidas_estao_declaradas(self):
        pares = {
            (i["total"], tuple(sorted(i["parcelas"])))
            for i in build_dataset.carrega_identidades()
        }
        self.assertIn(("sfn_total", ("sfn_pf", "sfn_pj")), pares)
        self.assertIn(("sfn_total", ("sfn_direcionado", "sfn_livre")), pares)
        self.assertIn(("conc_total", ("conc_pf", "conc_pj")), pares)
        industria = [i for i in build_dataset.carrega_identidades() if i["total"] == "ativ_industria"]
        self.assertEqual(len(industria), 1)
        # as mesmas dezesseis do seletor "Detalhar indústria" de abas.yaml
        detalhe = next(
            g["detalhe"]["por"]
            for _, g in build_dataset._graficos()
            if (g.get("detalhe") or {}).get("substitui") == "ativ_industria"
        )
        self.assertEqual(sorted(industria[0]["parcelas"]), sorted(detalhe))


class TestConfiguracaoDeProducao(unittest.TestCase):
    """Todas as verificações de config/ que `main` roda antes da coleta, sem rede."""

    def test_nenhuma_verificacao_aponta_problema(self):
        for titulo, problemas in build_dataset.confere_configuracao(
            build_dataset.catalogo_completo()
        ):
            self.assertEqual(problemas, [], f"{titulo}\n" + "\n".join(problemas))

    def test_ids_do_grafico_inclui_o_detalhe(self):
        grafico = {"series": ["a", "b"], "detalhe": {"por": ["c"], "substitui": "b"}}
        self.assertEqual(build_dataset.ids_do_grafico(grafico), ["a", "b", "c"])
        self.assertEqual(build_dataset.ids_do_grafico({"series": ["a"]}), ["a"])


class TestGuardAntesDosArtefatos(unittest.TestCase):
    """
    Com regressão, `main` sai com 2 sem escrever NADA.

    Antes ele escrevia tudo e só depois conferia: o manifest.json regredido virava a
    referência da execução seguinte, que passava. O guard só bloqueava uma vez.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = self.tmp / "data"
        self.docs = self.tmp / "docs"
        self.data.mkdir()
        self.docs.mkdir()
        anterior = {"series": [{"serie_id": "sfn_total", "status": "ok", "n_obs": 10}]}
        (self.data / "manifest.json").write_text(json.dumps(anterior), encoding="utf-8")
        self.antes = (self.data / "manifest.json").read_bytes()

        manifesto = [{"serie_id": "sfn_total", "status": "ausente", "n_obs": 0, "motivo": "x"}]
        mock.patch.object(build_dataset, "DATA", self.data).start()
        mock.patch.object(build_dataset, "DOCS", self.docs).start()
        mock.patch.object(build_dataset, "coleta_tudo", return_value=({}, manifesto, {})).start()
        mock.patch.object(
            build_dataset, "deriva_tudo", return_value=({"series": []}, {})
        ).start()
        mock.patch.object(build_dataset, "carrega_env").start()
        self.addCleanup(mock.patch.stopall)

    def test_regressao_sai_com_2_e_nao_escreve_nada(self):
        with mock.patch.object(sys, "argv", ["build_dataset.py"]):
            codigo = build_dataset.main()
        self.assertEqual(codigo, 2)
        self.assertEqual((self.data / "manifest.json").read_bytes(), self.antes)
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), ["manifest.json"])
        self.assertEqual(list(self.docs.iterdir()), [])


class TestUltimaColetaOk(unittest.TestCase):
    """`estado.json` só anda quando a rede trouxe dado novo."""

    ANTES = "2026-09-19T00:00:00+00:00"

    def test_do_cache_mantem_a_anterior(self):
        manifesto = [{"serie_id": "a", "status": "ok", "fonte": "BCB/SGS", "motivo": None}]
        self.assertEqual(build_dataset.ultima_coleta_ok(manifesto, True, self.ANTES), self.ANTES)

    def test_tudo_stale_mantem_a_anterior(self):
        manifesto = [{"serie_id": "a", "status": "stale", "fonte": "BCB/SGS", "motivo": "503"}]
        self.assertEqual(build_dataset.ultima_coleta_ok(manifesto, False, self.ANTES), self.ANTES)

    def test_so_derivada_ou_fonte_fora_do_recorte_nao_conta(self):
        manifesto = [
            {"serie_id": "d", "status": "ok", "fonte": "Derivado", "motivo": None},
            {"serie_id": "i", "status": "ok", "fonte": "BIS", "motivo": "fora do recorte"},
        ]
        self.assertEqual(build_dataset.ultima_coleta_ok(manifesto, False, self.ANTES), self.ANTES)

    def test_coleta_nova_anda(self):
        manifesto = [{"serie_id": "a", "status": "ok", "fonte": "BCB/SGS", "motivo": None}]
        self.assertNotEqual(build_dataset.ultima_coleta_ok(manifesto, False, self.ANTES), self.ANTES)


class TestHttpGet(unittest.TestCase):
    """`comum.http_get`: sem espera inútil no fim, e o último status na mensagem."""

    class _Resp:
        def __init__(self, status):
            self.status_code = status

    def test_nao_dorme_depois_da_ultima_tentativa_e_cita_o_status(self):
        with mock.patch.object(comum.requests, "request", return_value=self._Resp(503)), \
                mock.patch.object(comum.time, "sleep") as dorme:
            with self.assertRaises(comum.ErroDeRede) as ctx:
                comum.http_get("https://exemplo")
        self.assertEqual(dorme.call_count, comum.TENTATIVAS - 1)
        self.assertIn("HTTP 503", str(ctx.exception))
        self.assertNotIn("None", str(ctx.exception))

    def test_erro_de_rede_e_runtime_error(self):
        """Todo `except RuntimeError` existente continua pegando."""
        self.assertTrue(issubclass(comum.ErroDeRede, RuntimeError))

    def test_excecao_de_rede_aparece_na_mensagem(self):
        erro = comum.requests.ConnectionError("recusada")
        with mock.patch.object(comum.requests, "request", side_effect=erro), \
                mock.patch.object(comum.time, "sleep"):
            with self.assertRaises(comum.ErroDeRede) as ctx:
                comum.http_get("https://exemplo")
        self.assertIn("ConnectionError", str(ctx.exception))


class TestDataNasAbasBase(unittest.TestCase):
    """Nas abas `base_*` da planilha, a coluna de data é data, não texto."""

    def test_data_e_date(self):
        import datetime

        import build_xlsx

        payload = {
            "series": {
                "s": {
                    "bases": ["nominal", "real"],
                    "datas": ["2026-02-01", "2026-01-01"],
                    "valores": {"nominal": [2.0, 1.0]},
                }
            }
        }
        tabela = build_xlsx.tabela_da_base(payload, "nominal", "_nominal")
        self.assertIsInstance(tabela["data"].iloc[0], datetime.date)
        self.assertEqual(tabela["data"].iloc[0], datetime.date(2026, 1, 1))
        self.assertEqual(tabela["s_nominal"].tolist(), [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
