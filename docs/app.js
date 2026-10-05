/* Monitor de Crédito e Endividamento — montagem da página.
 *
 * Sem build step: lê `window.MONITOR`, gerado por src/build_dataset.py e carregado por
 * dados.js. O payload vem embutido num <script> justamente para que a página funcione
 * tanto por file:// quanto servida no GitHub Pages, com o mesmo código.
 *
 * Este arquivo NÃO interpreta dado. Não deflaciona, não divide pelo PIB, não calcula
 * variação, não completa lacuna, não arredonda valor armazenado. As cinco bases do
 * seletor chegam prontas do pipeline, cada uma como um vetor alinhado ao eixo de datas
 * da série; aqui só se escolhe qual vetor desenhar, recorta o intervalo e formata.
 *
 * Nenhum hex e nenhuma fonte literal: tudo vem de tokens.css, lido com getComputedStyle,
 * inclusive o que é passado ao ECharts. Trocar um token troca a página e os gráficos.
 */
(function () {
  'use strict';

  var MESES_TRI = { 1: '1º tri', 4: '2º tri', 7: '3º tri', 10: '4º tri' };
  var MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

  var ID_ABA_METODOLOGIA = 'metodologia';

  /* Folga à direita da plotagem para o rótulo de ponta. É o que sustenta a decisão de
     não ter legenda, então não pode ser um número chutado: um rótulo cortado é pior que
     uma legenda. A folga é MEDIDA a partir do texto mais longo que vai ser desenhado,
     com a fonte real, e limitada a uma fração da largura do cartão — passando disso, o
     gráfico viraria uma tira fina ao lado de uma lista de nomes. */
  var FOLGA_MIN = 76;
  var FOLGA_FRACAO_MAX = 0.42;

  // ------------------------------------------------------------------ tokens

  /* Os tokens são relidos a cada desenho porque o modo escuro troca todos eles sem
     recarregar a página. Guardar num objeto criado uma vez só deixaria os gráficos na
     paleta clara depois de o sistema virar para escuro. */
  function tokens() {
    var raiz = getComputedStyle(document.documentElement);
    function v(nome) { return raiz.getPropertyValue(nome).trim(); }
    return {
      bg: v('--bg'), surface: v('--surface'),
      ink: v('--ink'), ink2: v('--ink-2'), ink3: v('--ink-3'), line: v('--line'),
      fTexto: v('--f-texto'),
      /* A sombra do tooltip é a do cartão. O ECharts desenha o tooltip num <div> com
         estilo inline, que não enxerga `var()` do jeito que o CSS enxerga — por isso o
         valor resolvido vai pronto, e a impressão, que zera o token, zera a sombra. */
      sombra: v('--shadow-card') || 'none',
      serie: {
        total: v('--c-total'), pj: v('--c-pj'), pf: v('--c-pf'),
        livre: v('--c-livre'), dir: v('--c-dir'), alerta: v('--c-alerta'),
        outros: v('--c-outros'),
        'extra-1': v('--c-extra-1'), 'extra-2': v('--c-extra-2'),
        'extra-3': v('--c-extra-3'), 'extra-4': v('--c-extra-4'),
        'extra-5': v('--c-extra-5'), 'extra-6': v('--c-extra-6')
      }
    };
  }

  /* Rotação usada por série sem papel declarado no catálogo — as dezesseis aberturas da
     indústria, por exemplo. Só tokens fora da faixa semântica entram aqui: nenhum deles
     pode virar "a cor de PJ" por acidente num gráfico e significar outra coisa noutro. */
  var ROTACAO = ['extra-1', 'extra-2', 'extra-3', 'extra-4', 'extra-5', 'extra-6', 'outros'];

  function corDaSerie(serie, grafico, indice, tk) {
    var papel = (grafico.cores && grafico.cores[serie.serie_id]) || serie.cor;
    if (papel && tk.serie[papel]) return tk.serie[papel];
    return tk.serie[ROTACAO[indice % ROTACAO.length]];
  }

  /* Alfa sobre um token. O hex é lido do token, nunca escrito aqui — é o que permite o
     único gradiente do site (preenchimento sob a linha em gráfico de série única) sem
     abrir exceção à regra de não ter cor literal no código. */
  function comAlfa(cor, alfa) {
    var m = /^#([0-9a-f]{6})$/i.exec(cor);
    if (m) {
      var n = parseInt(m[1], 16);
      return 'rgba(' + (n >> 16 & 255) + ',' + (n >> 8 & 255) + ',' + (n & 255) + ',' + alfa + ')';
    }
    var rgb = /^rgba?\(([^)]+)\)$/.exec(cor);
    if (rgb) {
      var p = rgb[1].split(',').slice(0, 3).map(function (x) { return x.trim(); });
      return 'rgba(' + p.join(',') + ',' + alfa + ')';
    }
    return cor;
  }

  var semMovimento = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Medida de texto com a fonte de verdade, num canvas fora da tela. Estimar por
     "largura média do caractere" erra feio em fontes proporcionais — "Pessoas jurídicas"
     e "Capital de giro" têm o mesmo número de letras e larguras bem diferentes. */
  var _ctxMedida = null;
  function medeTexto(texto, tamanho, peso, familia) {
    if (!_ctxMedida) _ctxMedida = document.createElement('canvas').getContext('2d');
    _ctxMedida.font = (peso || 400) + ' ' + tamanho + 'px ' + familia;
    return _ctxMedida.measureText(texto).width;
  }

  /* Encurta pelo fim, com reticências, até caber. Usado só quando o nome da série não
     cabe nem na folga máxima — o valor numérico nunca é cortado. */
  function encurta(texto, limite, tamanho, peso, familia) {
    if (medeTexto(texto, tamanho, peso, familia) <= limite) return texto;
    var corte = texto;
    while (corte.length > 1 && medeTexto(corte + '…', tamanho, peso, familia) > limite) {
      corte = corte.slice(0, -1);
    }
    return corte.replace(/[\s·-]+$/, '') + '…';
  }

  // ------------------------------------------------------------------ formatação

  /* Uma casa decimal em TODO número exibido — eixo, rótulo de ponta e tooltip —, mesmo
     quando o valor é exato: 120,0, nunca 120. Decisão de 04/10/2026, que substitui a
     regra anterior (duas casas para %, uma para R$, casas aparadas no eixo). É só
     exibição: o CSV e a planilha seguem com o valor completo calculado pelo pipeline. */
  var CASAS = 1;

  /* `signDisplay: 'negative'` tira o sinal do zero arredondado: -0,04 sairia "-0,0", um
     número que não existe. Navegador que conhece `signDisplay` mas não o valor
     'negative' lança RangeError; o que não conhece a opção a ignora. Nos dois casos a
     formatação cai para a forma simples e o sinal do zero é tirado à mão. */
  var _formatoNumero = null;
  function numero(valor) {
    if (!_formatoNumero) {
      var base = { minimumFractionDigits: CASAS, maximumFractionDigits: CASAS };
      try {
        _formatoNumero = new Intl.NumberFormat('pt-BR',
          Object.assign({ signDisplay: 'negative' }, base));
      } catch (e) {
        _formatoNumero = new Intl.NumberFormat('pt-BR', base);
      }
    }
    var texto = _formatoNumero.format(valor);
    return /^[-−]0(,0+)?$/.test(texto) ? texto.slice(1) : texto;
  }

  /* Número no CSV: o valor inteiro, sem arredondar, com vírgula decimal. O arquivo usa
     ';' como separador e BOM justamente para abrir direto no Excel em português, e ali
     um ponto decimal vira texto ou, pior, milhar — 1.5 lido como 15. */
  function numeroCsv(valor) {
    return String(valor).replace('.', ',');
  }

  function rotuloData(iso, periodicidade) {
    var p = iso.split('-');
    var mes = parseInt(p[1], 10);
    if (periodicidade === 'A') return p[0];
    if (periodicidade === 'T') return (MESES_TRI[mes] || mes) + '/' + p[0];
    return MESES[mes - 1] + '/' + p[0];
  }

  function dataBr(iso) {
    if (!iso) return '';
    var p = String(iso).slice(0, 10).split('-');
    return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : iso;
  }

  function el(tag, classe, texto) {
    var e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto != null) e.textContent = texto;
    return e;
  }

  function anosAntes(iso, anos) {
    var p = iso.split('-');
    return (parseInt(p[0], 10) - anos) + '-' + p[1] + '-' + p[2];
  }

  /* Unidade curta para o topo do eixo. "R$ bilhões" vira "R$ bi".

     Em R$ constantes o mês-base fica no eixo ("R$ bi de ago/2026"): é móvel, muda a cada
     atualização, e a descrição da base promete que ele aparece ali. Com R$ constantes
     como base de abertura (04/10/2026), escondê-lo deixaria o leitor sem saber a preços
     de quando está o número.

     O acumulado em 12 meses é a exceção que precisa de caso próprio, e vem ANTES do teste
     genérico de "R$": um fluxo mensal e a sua soma de doze meses têm a mesma unidade e
     ordens de grandeza diferentes — R$ 737 bi contra R$ 8.375 bi no mesmo eixo "R$ bi".
     Sem a marca no eixo, a única pista de que a escala mudou seria o seletor. */
  function unidadeCurta(unidade) {
    if (!unidade) return '';
    if (unidade.indexOf('acumulados em 12 meses') >= 0) return 'R$ bi, 12m';
    var mesBase = /de ([a-z]{3}\/\d{4})$/.exec(unidade);
    if (unidade.indexOf('R$') >= 0 && mesBase) return 'R$ bi de ' + mesBase[1];
    if (unidade.indexOf('R$') >= 0) return 'R$ bi';
    if (unidade.indexOf('12 meses') >= 0) return '% 12m';
    if (unidade.indexOf('no mês') >= 0) return '% mês';
    if (unidade.indexOf('PIB') >= 0) return '% PIB';
    return '%';
  }

  // ------------------------------------------------------------------ séries

  function serieDoPayload(id, grafico) {
    var s = Object.assign({ serie_id: id }, window.MONITOR.series[id]);
    if (grafico.rotulos && grafico.rotulos[id]) s.rotulo = grafico.rotulos[id];
    return s;
  }

  /* Ligar o detalhe TROCA o gráfico: mostra só as aberturas do setor detalhado, sem as
     demais atividades e sem o total do próprio setor. Misturar níveis de agregação na
     mesma escala comprime as parcelas contra a base do gráfico. */
  function seriesDoGrafico(grafico, detalhe) {
    var ids = (detalhe && grafico.detalhe) ? grafico.detalhe.por.slice() : grafico.series.slice();
    return ids.map(function (id) { return serieDoPayload(id, grafico); });
  }

  function pontos(serie, base) {
    var valores = serie.valores[base] || serie.valores.nominal;
    var saida = [];
    for (var i = 0; i < serie.datas.length; i++) {
      if (valores[i] !== null && valores[i] !== undefined) saida.push([serie.datas[i], valores[i]]);
    }
    return saida;
  }

  function recorta(pares, de, ate) {
    return pares.filter(function (p) {
      return (!de || p[0] >= de) && (!ate || p[0] <= ate);
    });
  }

  function unidadeDe(series, base) {
    for (var i = 0; i < series.length; i++) {
      if (series[i].unidades[base]) return series[i].unidades[base];
    }
    return '';
  }

  function fonteDe(series) {
    var fontes = [];
    series.forEach(function (s) { if (fontes.indexOf(s.fonte) < 0) fontes.push(s.fonte); });
    return fontes.join(' e ');
  }

  // ------------------------------------------------------------------ intervalo

  /* Os anos são contados para trás a partir da ÚLTIMA observação do gráfico, não da data
     de hoje: as séries do BIS saem com um ou dois trimestres de defasagem, e "5 anos"
     contado do calendário deixaria a última faixa mais curta que as demais sem motivo. */
  function intervalo(reg, series) {
    if (reg.custom && (reg.custom.de || reg.custom.ate)) {
      return { de: reg.custom.de || null, ate: reg.custom.ate || null };
    }
    var fim = null;
    series.forEach(function (s) {
      var p = pontos(s, reg.base);
      if (p.length && (!fim || p[p.length - 1][0] > fim)) fim = p[p.length - 1][0];
    });
    var periodo = (window.MONITOR.periodos || []).filter(function (p) {
      return p.id === reg.periodo;
    })[0];
    if (!periodo || periodo.anos == null) return { de: reg.def.inicio || null, ate: null };
    return { de: fim ? anosAntes(fim, periodo.anos) : null, ate: null };
  }

  // ------------------------------------------------------------------ opção do ECharts

  function opcoes(reg, series, unidade, tk) {
    var periodicidade = series[0].periodicidade;
    var base = reg.base;
    var umaSerie = series.length === 1;

    /* Janela exibida, em anos. Acima de três, as marcas do eixo X caem só em virada de
       ano: sem isso, numa plotagem estreita (celular, visão expandida no celular) o
       ECharts descia para marcas semestrais e escrevia "Jul" entre os anos. */
    var primeiraData = null, ultimaData = null;
    series.forEach(function (s) {
      if (!s.visivel.length) return;
      var a = s.visivel[0][0], b = s.visivel[s.visivel.length - 1][0];
      if (!primeiraData || a < primeiraData) primeiraData = a;
      if (!ultimaData || b > ultimaData) ultimaData = b;
    });
    var ANO_MS = 365.25 * 24 * 3600 * 1000;
    var anosVisiveis = primeiraData ? (Date.parse(ultimaData) - Date.parse(primeiraData)) / ANO_MS : 0;
    var rotuloMenor = series.length > 5;

    /* Texto de cada rótulo de ponta, e a folga que ele exige.
     *
     * Três formas, na ordem de preferência, escolhidas pela largura disponível:
     *
     *   uma linha    "Total  7.372,0", o ideal — é o formato que a orientação pede
     *   duas linhas  nome em cima, valor embaixo, quando os dois lado a lado não cabem.
     *                A largura exigida passa a ser a do MAIOR dos dois, não a soma, o
     *                que costuma resolver os cartões estreitos de 4/12
     *   encurtado    nome com reticências, último recurso; o valor nunca é cortado
     *
     * A forma é escolhida para o gráfico inteiro, não por série: rótulos em formatos
     * diferentes na mesma ponta ficariam desalinhados entre si.
     */
    var tamanhoRotulo = rotuloMenor ? 12 : 13;
    var larguraCartao = reg.area.clientWidth || 600;
    var folgaMax = Math.max(FOLGA_MIN, Math.round(larguraCartao * FOLGA_FRACAO_MAX));
    var respiro = 18;

    var partes = series.map(function (s) {
      var ultimo = s.visivel[s.visivel.length - 1];
      return { id: s.serie_id, nome: s.rotulo, valor: numero(ultimo[1]) };
    });
    function larguraDe(texto) { return medeTexto(texto, tamanhoRotulo, 500, tk.fTexto); }

    var maiorUma = Math.max.apply(null, partes.map(function (p) {
      return larguraDe(p.nome + '  ' + p.valor);
    }));
    var maiorDuas = Math.max.apply(null, partes.map(function (p) {
      return Math.max(larguraDe(p.nome), larguraDe(p.valor));
    }));

    var textos = {}, folga, duasLinhas = false;
    if (maiorUma + respiro <= folgaMax) {
      folga = Math.ceil(maiorUma) + respiro;
      partes.forEach(function (p) { textos[p.id] = p.nome + '  ' + p.valor; });
    } else if (maiorDuas + respiro <= folgaMax) {
      duasLinhas = true;
      folga = Math.ceil(maiorDuas) + respiro;
      partes.forEach(function (p) { textos[p.id] = p.nome + '\n' + p.valor; });
    } else {
      duasLinhas = true;
      folga = folgaMax;
      var limite = folgaMax - respiro;
      partes.forEach(function (p) {
        // O valor nunca é cortado; só o nome.
        textos[p.id] = encurta(p.nome, limite, tamanhoRotulo, 500, tk.fTexto) + '\n' + p.valor;
      });
    }
    folga = Math.max(FOLGA_MIN, folga);

    var nominais = {};
    if (base === 'var12m' || base === 'var1m') {
      series.forEach(function (s) {
        var mapa = {};
        pontos(s, 'nominal').forEach(function (p) { mapa[p[0]] = p[1]; });
        nominais[s.rotulo] = { mapa: mapa, unidade: s.unidades.nominal };
      });
    }

    return {
      useUTC: true,
      backgroundColor: 'transparent',
      textStyle: { fontFamily: tk.fTexto },
      /* Sem animação de entrada; só a transição que responde a uma ação do leitor. */
      animation: !semMovimento,
      animationDuration: 0,
      animationDurationUpdate: semMovimento ? 0 : 250,
      animationEasingUpdate: 'cubicOut',

      grid: { left: 2, right: folga, top: 28, bottom: 4, containLabel: true },

      tooltip: {
        trigger: 'axis',
        confine: true,
        backgroundColor: tk.surface,
        borderColor: tk.line,
        borderWidth: 1,
        borderRadius: 10,
        padding: [10, 12],
        extraCssText: 'box-shadow: ' + tk.sombra + ';',
        // Crosshair vertical fino seguindo o mouse.
        axisPointer: { type: 'line', lineStyle: { color: tk.ink3, width: 1, type: 'solid' } },
        formatter: function (ps) {
          var iso = new Date(ps[0].value[0]).toISOString().slice(0, 10);
          var html = '<div class="tt__data">' + rotuloData(iso, periodicidade) + '</div>';
          ps.forEach(function (p) {
            var ref = nominais[p.seriesName];
            var extra = (ref && ref.mapa[iso] !== undefined)
              ? '<span class="tt__ref">de ' + numero(ref.mapa[iso]) + '</span>'
              : '';
            html += '<div class="tt__linha">'
              + '<span class="tt__marca" style="background:' + p.color + '"></span>'
              + '<span class="tt__nome">' + p.seriesName + '</span>'
              + extra
              + '<span class="tt__valor">' + numero(p.value[1]) + '</span>'
              + '</div>';
          });
          return html;
        }
      },

      xAxis: {
        type: 'time',
        // Sem título de eixo, sem grid vertical: as datas se explicam.
        /* Menos marcas em cartão estreito. `hideOverlap` sozinho não resolvia: num
           cartão de quatro colunas sobram ~200px de plotagem, e o ECharts encaixava oito
           anos que se encostavam sem chegar a se sobrepor — saía "201020132016..." como
           um número só. */
        splitNumber: larguraCartao < 460 ? 3 : 5,
        minInterval: anosVisiveis > 3 ? ANO_MS : undefined,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: {
          color: tk.ink3, fontSize: 12, fontFamily: tk.fTexto, hideOverlap: true,
          /* Rótulos em português. O ECharts usa o idioma padrão dele, inglês, nos nomes
             de mês ("Jul", "Feb") — apareciam no período de 1 ano e em tela estreita.
             Virada de ano vira o ano; qualquer outra marca, o mês abreviado — e, em
             janela de mais de três anos, nada: o ECharts põe marcas semestrais entre os
             anos mesmo com `minInterval` de um ano. */
          formatter: function (valor) {
            var d = new Date(valor);
            if (d.getUTCMonth() === 0) return String(d.getUTCFullYear());
            return anosVisiveis > 3 ? '' : MESES[d.getUTCMonth()];
          }
        }
      },

      yAxis: {
        type: 'value',
        scale: true,
        splitNumber: 4,
        // Unidade no topo do eixo, no lugar de um título de eixo.
        name: unidadeCurta(unidade),
        nameLocation: 'end',
        nameGap: 12,
        nameTextStyle: {
          color: tk.ink3, fontSize: 12, fontFamily: tk.fTexto,
          align: 'left', verticalAlign: 'bottom'
        },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: tk.line, width: 1 } },
        axisLabel: { color: tk.ink3, fontSize: 12, fontFamily: tk.fTexto, formatter: numero }
      },

      series: series.map(function (s, i) {
        var cor = corDaSerie(s, reg.def, i, tk);
        var total = s.papel === 'total';
        var residual = s.cor === 'outros';
        var ultimo = s.visivel[s.visivel.length - 1];

        return {
          name: s.rotulo,
          type: 'line',
          color: cor,
          showSymbol: false,
          symbol: 'circle',
          lineStyle: {
            width: total ? 2.5 : (residual ? 1.25 : 1.5),
            type: residual ? 'dashed' : 'solid',
            cap: 'round'
          },
          areaStyle: umaSerie ? {
            // Único gradiente do site: preenchimento sob a linha em série única.
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: comAlfa(cor, 0.12) },
                { offset: 1, color: comAlfa(cor, 0) }
              ]
            }
          } : undefined,
          /* Rótulo na ponta da linha, no lugar de legenda. `moveOverlap` empurra
             verticalmente quando dois colidem, em vez de esconder um deles. */
          endLabel: {
            show: true,
            formatter: textos[s.serie_id],
            color: cor,
            fontSize: tamanhoRotulo,
            fontWeight: 500,
            fontFamily: tk.fTexto,
            distance: 10,
            align: 'left',
            lineHeight: duasLinhas ? 15 : tamanhoRotulo + 2
          },
          labelLayout: { moveOverlap: 'shiftY', hideOverlap: false },
          emphasis: { focus: 'series' },
          blur: {
            lineStyle: { opacity: 0.25 },
            areaStyle: { opacity: 0.08 },
            label: { opacity: 0.25 },
            itemStyle: { opacity: 0.25 }
          },
          /* Marcador só no último ponto. Vazado quando o dado é preliminar na fonte —
             o mês mais recente das tabelas de crédito do BCB sai com asterisco. */
          markPoint: ultimo ? {
            silent: true,
            symbol: 'circle',
            symbolSize: s.preliminar ? 9 : 6,
            itemStyle: s.preliminar
              ? { color: tk.surface, borderColor: cor, borderWidth: 1.5 }
              : { color: cor },
            label: { show: false },
            data: [{ coord: ultimo }]
          } : undefined,
          data: s.visivel
        };
      })
    };
  }

  // ------------------------------------------------------------------ download

  function csv(reg, series, unidade, faixa) {
    var datas = {};
    series.forEach(function (s) { s.visivel.forEach(function (o) { datas[o[0]] = true; }); });
    var ordenadas = Object.keys(datas).sort();
    var indices = series.map(function (s) {
      var m = {};
      s.visivel.forEach(function (o) { m[o[0]] = o[1]; });
      return m;
    });
    /* Gráfico sem bases (série já em %) mostra o valor da fonte, mas `reg.base` continua
       'nominal' por padrão — o cabeçalho diria "R$ correntes" e as colunas levariam
       `_nominal` numa taxa de inadimplência. Sem bases declaradas, não há base. */
    var base = reg.def.bases && reg.def.bases.length
      ? (window.MONITOR.bases || []).filter(function (b) { return b.id === reg.base; })[0]
      : null;
    var sufixo = base ? base.sufixo : '';

    var linhas = [['data'].concat(series.map(function (s) { return s.serie_id + sufixo; })).join(';')];
    ordenadas.forEach(function (d) {
      linhas.push([d].concat(indices.map(function (m) {
        return m[d] === undefined ? '' : numeroCsv(m[d]);
      })).join(';'));
    });

    return [
      '# ' + reg.def.titulo,
      '# base: ' + (base ? base.rotulo : 'valores da fonte'),
      '# unidade: ' + unidade,
      '# fonte: ' + fonteDe(series),
      '# intervalo exibido: ' + (faixa.de || 'início da série') + ' a ' + (faixa.ate || 'último dado'),
      '# a planilha XLSX traz cada série inteira, desde a primeira observação da fonte',
      '# gerado do Monitor de Crédito e Endividamento em ' + window.MONITOR.gerado_em
    ].join('\n') + '\n' + linhas.join('\n') + '\n';
  }

  function baixaUrl(nome, url) {
    var a = document.createElement('a');
    a.href = url;
    a.download = nome;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function baixaTexto(nome, conteudo) {
    var url = URL.createObjectURL(new Blob(['﻿' + conteudo], { type: 'text/csv;charset=utf-8' }));
    baixaUrl(nome, url);
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function nomeArquivo(titulo, ext) {
    return titulo.toLowerCase().normalize('NFD')
      .replace(new RegExp('[\\u0300-\\u036f]', 'g'), '')
      .replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') + '.' + ext;
  }

  /* O PNG usa exatamente os mesmos tokens da tela — o ECharts exporta o que desenhou —
     e recebe título e procedência desenhados em volta, para que a imagem continue
     dizendo o que é e de onde veio depois de sair do site. */
  /* Quebra um texto em linhas que caibam em `limite`, com a fonte já posta em `ctx`.
     Palavra que sozinha passa do limite fica numa linha própria; quem chama reduz a
     fonte nesse caso, em vez de cortar. */
  function quebraLinhas(ctx, texto, limite) {
    var linhas = [], atual = '';
    texto.split(/\s+/).forEach(function (palavra) {
      var tentativa = atual ? atual + ' ' + palavra : palavra;
      if (atual && ctx.measureText(tentativa).width > limite) {
        linhas.push(atual);
        atual = palavra;
      } else {
        atual = tentativa;
      }
    });
    if (atual) linhas.push(atual);
    return linhas;
  }

  /* Maior fonte, do tamanho pedido para baixo, em que nenhuma linha passa do limite. Um
     título longo ("Concessões de crédito livre às empresas por modalidade") num cartão
     estreito quebra em duas linhas; só se nem assim couber a fonte diminui. */
  function blocoDeTexto(ctx, texto, limite, tamanho, peso, familia) {
    var linhas;
    for (;;) {
      ctx.font = peso + ' ' + tamanho + 'px ' + familia;
      linhas = quebraLinhas(ctx, texto, limite);
      var cabe = linhas.every(function (l) { return ctx.measureText(l).width <= limite; });
      if (cabe || tamanho <= 12) break;
      tamanho -= 2;
    }
    return { linhas: linhas, fonte: ctx.font, altura: Math.round(tamanho * 1.3) };
  }

  /* A imagem sai de uma instância TEMPORÁRIA, em canvas, e não da que está na tela. Os
     gráficos da página usam o renderizador SVG, e nele `getDataURL` devolve SVG em 1x,
     ignorando `pixelRatio` e `backgroundColor` — o título e a procedência, desenhados
     para 2x, saíam cortados, e o SVG carregado como <img> perde as fontes da web. A
     instância temporária tem o tamanho exato da área do cartão, para que a folga do
     rótulo de ponta, medida para essa largura, continue valendo, e é descartada logo
     depois. */
  function png(reg) {
    if (!reg.opcao || typeof echarts === 'undefined') return;
    var tk = tokens();
    var largura = reg.area.clientWidth || 800;
    var altura = reg.area.clientHeight || 400;

    var fora = document.createElement('div');
    fora.setAttribute('aria-hidden', 'true');
    fora.style.position = 'fixed';
    fora.style.left = '-10000px';
    fora.style.top = '0';
    fora.style.width = largura + 'px';
    fora.style.height = altura + 'px';
    document.body.appendChild(fora);

    var url = null, temporaria = null;
    try {
      temporaria = echarts.init(fora, null, { renderer: 'canvas', width: largura, height: altura });
      temporaria.setOption(Object.assign({}, reg.opcao, { animation: false }), true);
      url = temporaria.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: tk.surface });
    } finally {
      if (temporaria) temporaria.dispose();
      document.body.removeChild(fora);
    }
    if (!url) return;

    var img = new Image();
    img.onload = function () {
      var margem = 32, respiro = 20;
      var cv = document.createElement('canvas');
      var ctx = cv.getContext('2d');
      var limite = img.width - 2 * margem;
      var titulo = blocoDeTexto(ctx, reg.def.titulo, limite, 32, 500, tk.fTexto);
      var rodape = blocoDeTexto(ctx,
        'Fonte: ' + fonteDe(reg.seriesVisiveis) + ' · Monitor de Crédito e Endividamento',
        limite, 24, 400, tk.fTexto);
      var topo = margem + titulo.linhas.length * titulo.altura + respiro;
      var base = respiro + rodape.linhas.length * rodape.altura + margem;

      // Mudar o tamanho do canvas zera o contexto, fonte inclusive: tudo é reposto depois.
      cv.width = img.width;
      cv.height = img.height + topo + base;
      ctx.fillStyle = tk.surface;
      ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.drawImage(img, 0, topo);
      ctx.textBaseline = 'top';

      ctx.fillStyle = tk.ink;
      ctx.font = titulo.fonte;
      titulo.linhas.forEach(function (l, i) { ctx.fillText(l, margem, margem + i * titulo.altura); });

      ctx.fillStyle = tk.ink3;
      ctx.font = rodape.fonte;
      var y0 = img.height + topo + respiro;
      rodape.linhas.forEach(function (l, i) { ctx.fillText(l, margem, y0 + i * rodape.altura); });

      baixaUrl(nomeArquivo(reg.def.titulo, 'png'), cv.toDataURL('image/png'));
    };
    img.src = url;
  }

  // ------------------------------------------------------------------ estado

  var registros = {};
  var botoesAba = {};
  var paineis = {};
  var instancias = [];

  // ------------------------------------------------------------------ controles

  function seletorBase(reg) {
    var bases = (window.MONITOR.bases || []).filter(function (b) {
      return reg.def.bases.indexOf(b.id) >= 0;
    });
    // Gráfico que não admite troca de base não ganha seletor desabilitado: não ganha nada.
    if (bases.length < 2) return null;

    var sel = el('select', 'pilula');
    sel.setAttribute('aria-label', 'Base de valores');
    bases.forEach(function (b) {
      var o = el('option', null, b.rotulo);
      o.value = b.id;
      if (b.id === reg.base) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener('change', function () {
      reg.base = sel.value;
      desenha(reg);
    });
    return sel;
  }

  var CURTO = { tudo: 'Tudo', a10: '10a', a5: '5a', a3: '3a', a1: '1a' };

  /* Grupo segmentado: `Tudo | 10a | 5a | 3a | 1a | ⋯`. O "⋯" abre dois campos mês/ano.
     Sem range slider — polui. */
  function seletorPeriodo(inicial, aoEscolher) {
    var grupo = el('div', 'segmentado');
    grupo.setAttribute('role', 'group');
    grupo.setAttribute('aria-label', 'Período');
    var itens = {};

    (window.MONITOR.periodos || []).forEach(function (p) {
      var b = el('button', 'segmentado__item', CURTO[p.id] || p.rotulo);
      b.type = 'button';
      b.setAttribute('aria-pressed', p.id === inicial ? 'true' : 'false');
      b.addEventListener('click', function () { aoEscolher(p.id); });
      grupo.appendChild(b);
      itens[p.id] = b;
    });

    var custom = el('button', 'segmentado__item', '⋯');
    custom.type = 'button';
    custom.title = 'Intervalo personalizado';
    custom.setAttribute('aria-pressed', 'false');
    custom.addEventListener('click', function () { aoEscolher('__custom'); });
    grupo.appendChild(custom);
    itens.__custom = custom;

    return {
      elemento: grupo,
      marca: function (ativo) {
        Object.keys(itens).forEach(function (k) {
          itens[k].setAttribute('aria-pressed', k === ativo ? 'true' : 'false');
        });
      }
    };
  }

  function camposIntervalo(aoAplicar) {
    var caixa = el('div', 'intervalo');
    caixa.hidden = true;
    var de = el('input'); de.type = 'month'; de.setAttribute('aria-label', 'Mês inicial');
    var ate = el('input'); ate.type = 'month'; ate.setAttribute('aria-label', 'Mês final');
    caixa.appendChild(el('span', null, 'de'));
    caixa.appendChild(de);
    caixa.appendChild(el('span', null, 'até'));
    caixa.appendChild(ate);
    function aplica() {
      aoAplicar({
        de: de.value ? de.value + '-01' : null,
        ate: ate.value ? ate.value + '-01' : null
      });
    }
    de.addEventListener('change', aplica);
    ate.addEventListener('change', aplica);
    return { caixa: caixa, de: de, ate: ate };
  }

  function iconeInfo(reg) {
    var grafico = reg.def;
    if (!grafico.metodologia) return null;
    var b = el('button', 'info', 'i');
    b.type = 'button';
    b.title = 'Nota metodológica';
    b.setAttribute('aria-label', 'Nota metodológica de ' + grafico.titulo);
    b.addEventListener('click', function () {
      /* Dentro do gráfico expandido, a Metodologia abriria ATRÁS do modal, invisível.
         Fecha antes, como faz o link da coluna de notas. */
      if (reg.expandido) fechaDialogo();
      vaiParaMetodologia(grafico.metodologia);
    });
    return b;
  }

  var SETA_BAIXO =
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
    '<path d="M8 2.5v8m0 0 3.2-3.2M8 10.5 4.8 7.3M3 13.5h10" stroke="currentColor" ' +
    'stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function menuDownload(reg) {
    var caixa = el('div', 'baixar');
    var botao = el('button', 'baixar__botao');
    botao.type = 'button';
    botao.innerHTML = SETA_BAIXO;
    botao.title = 'Baixar';
    botao.setAttribute('aria-label', 'Baixar ' + reg.def.titulo);
    botao.setAttribute('aria-expanded', 'false');

    var menu = el('div', 'baixar__menu');
    menu.hidden = true;

    function fecha() {
      menu.hidden = true;
      botao.setAttribute('aria-expanded', 'false');
      document.removeEventListener('click', foraDaqui, true);
      document.removeEventListener('keydown', comEsc, true);
    }
    function foraDaqui(ev) { if (!caixa.contains(ev.target)) fecha(); }
    /* Esc fecha só o menu. O `preventDefault` impede que a mesma tecla feche também o
       gráfico expandido quando o menu foi aberto dentro dele: o <dialog> só pede o
       fechamento se o keydown não tiver sido cancelado. */
    function comEsc(ev) {
      if (ev.key !== 'Escape') return;
      ev.preventDefault();
      ev.stopPropagation();
      var focoDentro = caixa.contains(document.activeElement);
      fecha();
      if (focoDentro) botao.focus();
    }
    reg.fechaMenu = fecha;
    function item(texto, acao) {
      var b = el('button', 'baixar__item', texto);
      b.type = 'button';
      b.addEventListener('click', function () { fecha(); acao(); });
      return b;
    }

    menu.appendChild(item('Imagem (PNG)', function () { png(reg); }));
    menu.appendChild(item('Dados (CSV)', function () {
      baixaTexto(nomeArquivo(reg.def.titulo, 'csv'),
        csv(reg, reg.seriesVisiveis, reg.unidadeAtual, reg.faixaAtual));
    }));

    botao.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var abrir = menu.hidden;
      menu.hidden = !abrir;
      botao.setAttribute('aria-expanded', abrir ? 'true' : 'false');
      if (abrir) {
        document.addEventListener('click', foraDaqui, true);
        document.addEventListener('keydown', comEsc, true);
      } else {
        fecha();
      }
    });

    caixa.appendChild(botao);
    caixa.appendChild(menu);
    return caixa;
  }

  // ------------------------------------------------------------------ cartão

  function montaCartao(grafico, abaId) {
    var cartao = el('section', 'cartao');

    var topo = el('div', 'cartao__topo');
    topo.appendChild(el('h3', 'cartao__titulo', grafico.titulo));
    var controles = el('div', 'cartao__controles');
    topo.appendChild(controles);
    cartao.appendChild(topo);

    var area = el('div', 'cartao__area');
    area.appendChild(el('div', 'esqueleto'));
    cartao.appendChild(area);

    var reg = {
      abaId: abaId, def: grafico, cartao: cartao, area: area,
      base: grafico.base_padrao || 'nominal',
      periodo: window.MONITOR.periodo_padrao,
      custom: null, detalhe: false,
      instancia: null, opcao: null,
      seriesVisiveis: [], unidadeAtual: '', faixaAtual: { de: null, ate: null }
    };

    var base = seletorBase(reg);
    if (base) controles.appendChild(base);

    var campos = camposIntervalo(function (v) { reg.custom = v; desenha(reg); });
    var periodo = seletorPeriodo(reg.periodo, function (id) {
      periodo.marca(id);
      if (id === '__custom') { campos.caixa.hidden = false; return; }
      campos.caixa.hidden = true;
      reg.custom = null;
      reg.periodo = id;
      desenha(reg);
    });
    reg.periodoUI = periodo;
    reg.campos = campos;
    controles.appendChild(periodo.elemento);
    controles.appendChild(campos.caixa);

    if (grafico.detalhe) {
      var alternar = el('button', 'pilula', grafico.detalhe.rotulo);
      alternar.type = 'button';
      alternar.setAttribute('aria-pressed', 'false');
      alternar.addEventListener('click', function () {
        reg.detalhe = !reg.detalhe;
        alternar.setAttribute('aria-pressed', reg.detalhe ? 'true' : 'false');
        desenha(reg);
      });
      controles.appendChild(alternar);
    }

    var info = iconeInfo(reg);
    if (info) controles.appendChild(info);
    var expande = botaoIcone('expande', ICONE.expande, 'Expandir o gráfico');
    expande.addEventListener('click', function () { abreExpandido(reg); });
    // Para onde o foco volta quando o gráfico expandido fecha.
    reg.botaoExpande = expande;
    controles.appendChild(expande);
    controles.appendChild(menuDownload(reg));

    // Clique no próprio gráfico também expande — é o gesto que o leitor tenta primeiro.
    area.addEventListener('click', function () { if (!reg.expandido) abreExpandido(reg); });

    return reg;
  }

  function erroNoCartao(reg, mensagem) {
    reg.area.innerHTML = '';
    reg.area.appendChild(el('p', 'cartao__erro', mensagem));
  }

  function desenha(reg) {
    var tk = tokens();
    var series = seriesDoGrafico(reg.def, reg.detalhe);
    var faixa = intervalo(reg, series);
    var unidade = unidadeDe(series, reg.base);

    series.forEach(function (s) { s.visivel = recorta(pontos(s, reg.base), faixa.de, faixa.ate); });

    // Intervalo que não pega observação nenhuma: melhor a série inteira que um vazio.
    if (series.every(function (s) { return !s.visivel.length; })) {
      series.forEach(function (s) { s.visivel = pontos(s, reg.base); });
      faixa = { de: null, ate: null };
    }
    series = series.filter(function (s) { return s.visivel.length; });

    if (!series.length) {
      erroNoCartao(reg, 'Nenhuma série deste gráfico carregou. Tente recarregar a página.');
      return;
    }

    reg.seriesVisiveis = series;
    reg.unidadeAtual = unidade;
    reg.faixaAtual = faixa;
    reg.opcao = opcoes(reg, series, unidade, tk);
    if (reg.instancia) reg.instancia.setOption(reg.opcao, true);
    if (reg.expandido) preencheNotas(reg);
  }

  function inicializa(reg) {
    if (reg.instancia) return;
    if (typeof echarts === 'undefined') {
      erroNoCartao(reg, 'A biblioteca de gráficos não carregou. Os dados seguem disponíveis no download.');
      return;
    }
    reg.area.innerHTML = '';
    reg.instancia = echarts.init(reg.area, null, { renderer: 'svg' });
    /* Redesenha agora que o cartão tem largura real. A folga do rótulo de ponta é medida
       a partir dela, e um elemento oculto mede zero — a opção calculada na montagem
       reservaria a folga mínima e cortaria os rótulos. */
    desenha(reg);
    instancias.push(reg.instancia);
  }

  // ------------------------------------------------------------------ carrossel

  /* Dois gráficos por vez, do mesmo tamanho, numa faixa com barra de rolagem horizontal
     — decisão de 04/10/2026, que substitui a grade de doze colunas. Em tela estreita o
     CSS põe um por vez, e tudo aqui é medido, não suposto: quantos cabem na tela sai da
     largura real dos cartões.

     A cada INTERVALO a faixa avança uma tela e, no fim, volta ao começo. A rotação fica
     suspensa enquanto o ponteiro está sobre a faixa ou o foco de teclado está dentro
     dela: um gráfico não pode sair da tela no meio da leitura de um tooltip ou da troca
     de base. O botão de pausa a desliga de vez, e passar à mão também — quem escolhe ir
     no próprio ritmo não quer ser atropelado cinco segundos depois. Com movimento reduzido
     pedido pelo sistema, a faixa já abre pausada. */
  var INTERVALO = 5000;
  var carrosseis = {};

  var ICONE = {
    anterior: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
      '<path d="M10 3.5 5.5 8l4.5 4.5" stroke="currentColor" stroke-width="1.5" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    proximo: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
      '<path d="M6 3.5 10.5 8 6 12.5" stroke="currentColor" stroke-width="1.5" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    pausa: '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">' +
      '<rect x="2.5" y="2" width="2.5" height="8" rx=".75" fill="currentColor"/>' +
      '<rect x="7" y="2" width="2.5" height="8" rx=".75" fill="currentColor"/></svg>',
    toca: '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">' +
      '<path d="M3.5 2.2v7.6a.6.6 0 0 0 .9.5l6-3.8a.6.6 0 0 0 0-1L4.4 1.7a.6.6 0 0 0-.9.5Z" ' +
      'fill="currentColor"/></svg>',
    expande: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
      '<path d="M9.5 2.5h4v4M6.5 13.5h-4v-4M13.5 2.5 9 7M2.5 13.5 7 9" stroke="currentColor" ' +
      'stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    fecha: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
      '<path d="m3.5 3.5 9 9m0-9-9 9" stroke="currentColor" stroke-width="1.5" ' +
      'stroke-linecap="round"/></svg>'
  };

  function botaoIcone(classe, svg, rotulo) {
    var b = el('button', classe);
    b.type = 'button';
    b.innerHTML = svg;
    b.title = rotulo;
    b.setAttribute('aria-label', rotulo);
    return b;
  }

  /* Distância entre o início de dois cartões vizinhos: largura mais vão, sem precisar
     ler o vão do CSS. */
  function passoDe(c) {
    var cs = c.regs.map(function (r) { return r.cartao; });
    if (cs.length > 1) return cs[1].offsetLeft - cs[0].offsetLeft;
    return c.trilho.clientWidth || 1;
  }

  function porTelaDe(c) {
    return Math.max(1, Math.round(c.trilho.clientWidth / passoDe(c)));
  }

  function maximoDe(c) {
    return Math.max(0, c.trilho.scrollWidth - c.trilho.clientWidth);
  }

  function indiceDe(c) {
    return Math.round(c.trilho.scrollLeft / passoDe(c));
  }

  function rolavel(c) {
    return maximoDe(c) > 1;
  }

  function vaiPara(c, indice, suave) {
    var esquerda = Math.min(indice * passoDe(c), maximoDe(c));
    c.trilho.scrollTo({ left: esquerda, behavior: suave && !semMovimento ? 'smooth' : 'auto' });
  }

  /* No fim da faixa, volta ao começo; no começo, `anterior` vai ao fim. A última tela de
     uma aba com número ímpar de gráficos repete um gráfico da tela anterior — a faixa
     para no fim em vez de mostrar meio cartão vazio. */
  function avanca(c, sentido) {
    var k = porTelaDe(c), i = indiceDe(c);
    var noFim = c.trilho.scrollLeft >= maximoDe(c) - 2;
    var noInicio = c.trilho.scrollLeft <= 2;
    if (sentido > 0) vaiPara(c, noFim ? 0 : i + k, true);
    else vaiPara(c, noInicio ? c.regs.length - k : Math.max(0, i - k), true);
  }

  function atualizaBarra(c) {
    var n = c.regs.length, k = porTelaDe(c), i = Math.min(indiceDe(c), Math.max(0, n - k));
    c.barra.hidden = !rolavel(c);
    var texto = (k > 1 ? (i + 1) + '–' + Math.min(n, i + k) : String(i + 1)) + ' de ' + n;
    // Só escreve quando muda: reescrever o mesmo texto numa região viva pode reanunciá-lo.
    if (c.posicao.textContent !== texto) c.posicao.textContent = texto;
    c.indice = i;
  }

  function marcaPausa(c) {
    var rotulo = c.pausado ? 'Retomar' : 'Pausar';
    c.pausa.innerHTML = (c.pausado ? ICONE.toca : ICONE.pausa) + '<span>' + rotulo + '</span>';
    c.pausa.setAttribute('aria-label', (c.pausado ? 'Retomar' : 'Pausar') + ' a rotação automática');
    c.pausa.setAttribute('aria-pressed', c.pausado ? 'true' : 'false');
    /* Rotação em curso não é anunciada a cada troca; parada, a troca é ação do leitor.
       A região viva é só o "3–4 de 11", nunca a faixa: dentro dela estão os gráficos, e
       cada redesenho — tema, largura, fonte que chegou — seria lido em voz alta. */
    c.posicao.setAttribute('aria-live', c.pausado ? 'polite' : 'off');
  }

  /* Barra de progresso: enche em INTERVALO e a troca acontece quando ela fecha. Parada
     ou suspensa, volta a zero — a contagem recomeça inteira quando a rotação volta, e a
     barra mostra exatamente isso. */
  function progresso(c, correndo) {
    var f = c.progresso;
    f.style.transition = 'none';
    f.style.transform = 'scaleX(0)';
    if (!correndo) return;
    void f.offsetWidth; // fixa o zero antes de animar, senão o navegador pula direto
    f.style.transition = 'transform ' + INTERVALO + 'ms linear';
    f.style.transform = 'scaleX(1)';
  }

  function agenda(c) {
    clearTimeout(c.temporizador);
    c.temporizador = null;
    var corre = c.ativo && !c.pausado && !c.suspenso && !modalAberto && !document.hidden &&
      rolavel(c);
    progresso(c, corre);
    if (!corre) return;
    c.temporizador = setTimeout(function () {
      avanca(c, 1);
      agenda(c);
    }, INTERVALO);
  }

  function montaCarrossel(abaId, regs) {
    var caixa = el('div', 'carrossel');
    var trilho = el('div', 'trilho');
    trilho.tabIndex = 0;
    trilho.setAttribute('role', 'region');
    trilho.setAttribute('aria-roledescription', 'carrossel');
    trilho.setAttribute('aria-label', 'Gráficos desta aba');
    regs.forEach(function (r) { trilho.appendChild(r.cartao); });

    var barra = el('div', 'carrossel__barra');
    var anterior = botaoIcone('carrossel__seta', ICONE.anterior, 'Gráficos anteriores');
    var proximo = botaoIcone('carrossel__seta', ICONE.proximo, 'Próximos gráficos');
    var pausa = el('button', 'pilula carrossel__pausa');
    pausa.type = 'button';
    var posicao = el('span', 'carrossel__posicao');
    posicao.setAttribute('aria-atomic', 'true');
    var comandos = el('div', 'carrossel__comandos');
    comandos.appendChild(anterior);
    comandos.appendChild(posicao);
    comandos.appendChild(proximo);
    comandos.appendChild(pausa);
    var trilhaProgresso = el('div', 'carrossel__progresso');
    trilhaProgresso.setAttribute('aria-hidden', 'true');
    var progressoFill = el('span');
    trilhaProgresso.appendChild(progressoFill);
    barra.appendChild(comandos);
    barra.appendChild(trilhaProgresso);

    caixa.appendChild(trilho);
    caixa.appendChild(barra);

    var c = {
      abaId: abaId, caixa: caixa, trilho: trilho, barra: barra, pausa: pausa,
      posicao: posicao, progresso: progressoFill, regs: regs, indice: 0,
      pausado: semMovimento, suspenso: false, ativo: false, temporizador: null,
      ponteiroDentro: false
    };

    function manual(sentido) {
      c.pausado = true;
      marcaPausa(c);
      agenda(c);
      avanca(c, sentido);
    }
    anterior.addEventListener('click', function () { manual(-1); });
    proximo.addEventListener('click', function () { manual(1); });
    pausa.addEventListener('click', function () {
      c.pausado = !c.pausado;
      marcaPausa(c);
      agenda(c);
    });

    // Setas do teclado com o foco na faixa: uma tela por toque, como os botões.
    trilho.addEventListener('keydown', function (ev) {
      if (ev.target !== trilho) return;
      if (ev.key === 'ArrowRight') { ev.preventDefault(); manual(1); }
      if (ev.key === 'ArrowLeft') { ev.preventDefault(); manual(-1); }
    });

    var quadro = null;
    trilho.addEventListener('scroll', function () {
      if (quadro) return;
      quadro = requestAnimationFrame(function () { quadro = null; atualizaBarra(c); });
    }, { passive: true });

    function suspende(sim) { c.suspenso = sim; agenda(c); }
    /* Só o ponteiro de MOUSE suspende. No celular o toque dispara um `mouseenter` de
       compatibilidade e nunca o `mouseleave` correspondente: a faixa ficava suspensa
       para sempre, e "Retomar" não fazia nada. Pelo `pointerType` o toque fica de fora;
       o `touchstart` lá embaixo cuida dele. */
    caixa.addEventListener('pointerenter', function (ev) {
      if (ev.pointerType !== 'mouse') return;
      c.ponteiroDentro = true;
      suspende(true);
    });
    caixa.addEventListener('pointerleave', function (ev) {
      if (ev.pointerType !== 'mouse') return;
      c.ponteiroDentro = false;
      suspende(caixa.contains(document.activeElement) && focoDeTeclado(document.activeElement));
    });
    /* Só o foco de TECLADO suspende. O de mouse fica no botão clicado até o próximo
       clique fora, e prenderia a rotação parada depois de um simples "Retomar". */
    caixa.addEventListener('focusin', function (ev) { if (focoDeTeclado(ev.target)) suspende(true); });
    caixa.addEventListener('focusout', function (ev) {
      if (!caixa.contains(ev.relatedTarget) && !c.ponteiroDentro) suspende(false);
    });
    // No toque não há "sair de cima": cada toque reinicia a contagem.
    caixa.addEventListener('touchstart', function () { agenda(c); }, { passive: true });

    marcaPausa(c);
    carrosseis[abaId] = c;
    return caixa;
  }

  function focoDeTeclado(alvo) {
    try { return !!alvo && alvo.matches(':focus-visible'); } catch (e) { return false; }
  }

  // ------------------------------------------------------------------ expandido

  /* Clicar num gráfico abre o MESMO cartão em tela cheia, num <dialog>, com uma coluna de
     metodologia ao lado (decisão de 04/10/2026). O cartão é movido, não copiado: base,
     período, detalhe e download continuam funcionando, e o que o leitor muda lá dentro
     vale ao voltar para a faixa. Um marcador do mesmo tamanho guarda o lugar dele.

     A coluna de metodologia NÃO tem texto escrito para ela. Tudo vem do que já existe:
     os primeiros parágrafos da seção da Metodologia para a qual o "i" aponta, a descrição
     da base em config/abas.yaml e a ficha de cada série, gerada do catálogo. Resumo, aqui,
     é recorte mecânico — dois parágrafos e um link para a nota inteira —, nunca paráfrase.
     Ver o princípio 6 do CLAUDE.md. */
  var PARAGRAFOS_RESUMO = 2;
  var modalAberto = false;
  var dialogo = null;

  function montaDialogo() {
    var d = el('dialog', 'expandido');
    d.setAttribute('aria-label', 'Gráfico expandido');
    var fechar = botaoIcone('expandido__fechar', ICONE.fecha, 'Fechar');
    fechar.addEventListener('click', fechaDialogo);
    var corpo = el('div', 'expandido__corpo');
    var lugar = el('div', 'expandido__grafico');
    var notas = el('aside', 'expandido__notas');
    corpo.appendChild(lugar);
    corpo.appendChild(notas);
    d.appendChild(fechar);
    d.appendChild(corpo);

    // Clique no fundo escurecido fecha; clique dentro do conteúdo, não.
    d.addEventListener('click', function (ev) { if (ev.target === d) fechaDialogo(); });
    /* Esc dispara `cancel` na hora; o `close` que vem depois é enfileirado e, com a aba
       em segundo plano, chegou a não ser entregue — o cartão ficava preso no diálogo.
       Por isso cada saída devolve o cartão diretamente, e o `close` fica só de rede. */
    d.addEventListener('cancel', function (ev) { ev.preventDefault(); fechaDialogo(); });
    d.addEventListener('close', fechaExpandido);

    document.body.appendChild(d);
    dialogo = {
      elemento: d, corpo: corpo, lugar: lugar, notas: notas, reg: null, marcador: null
    };
  }

  function abreExpandido(reg) {
    if (!dialogo || modalAberto || typeof dialogo.elemento.showModal !== 'function') return;
    if (reg.fechaMenu) reg.fechaMenu();
    var marcador = el('div', 'cartao cartao--marcador');
    marcador.style.height = reg.cartao.offsetHeight + 'px';
    reg.cartao.replaceWith(marcador);
    dialogo.lugar.appendChild(reg.cartao);
    reg.cartao.classList.add('cartao--expandido');
    reg.expandido = true;
    dialogo.reg = reg;
    dialogo.marcador = marcador;
    modalAberto = true;
    /* O ponteiro agora está sobre o modal, e o foco que estava no botão de expandir saiu
       da faixa junto com o cartão — sem `focusout`, em alguns navegadores. Nenhum dos
       dois pode deixar a faixa suspensa: o estado é refeito ao fechar. */
    Object.keys(carrosseis).forEach(function (k) {
      carrosseis[k].ponteiroDentro = false;
      carrosseis[k].suspenso = false;
      agenda(carrosseis[k]);
    });

    dialogo.elemento.setAttribute('aria-label', 'Gráfico expandido: ' + reg.def.titulo);
    dialogo.elemento.showModal();
    dialogo.notas.scrollTop = 0;
    dialogo.corpo.scrollTop = 0;
    // A largura mudou: a folga do rótulo de ponta e o eixo têm de ser recalculados.
    if (reg.instancia) reg.instancia.resize();
    desenha(reg);
  }

  function fechaDialogo() {
    if (dialogo.elemento.open) dialogo.elemento.close();
    fechaExpandido();
  }

  function fechaExpandido() {
    var reg = dialogo && dialogo.reg;
    if (!reg) return;
    if (reg.fechaMenu) reg.fechaMenu();
    reg.cartao.classList.remove('cartao--expandido');
    dialogo.marcador.replaceWith(reg.cartao);
    reg.expandido = false;
    dialogo.reg = null;
    dialogo.marcador = null;
    modalAberto = false;
    if (reg.instancia) reg.instancia.resize();
    desenha(reg);

    /* Foco de volta a quem abriu. O <dialog> tenta devolvê-lo sozinho, mas o elemento
       que tinha o foco antes de abrir — o botão de expandir — foi junto com o cartão
       para dentro do modal e, no fechamento, estava num elemento oculto: o foco caía no
       <body>, e quem navega por teclado voltava ao topo da página. Só age se o foco não
       foi parar em outro lugar de propósito. */
    var ativo = document.activeElement;
    if (reg.botaoExpande && (!ativo || ativo === document.body || dialogo.elemento.contains(ativo))) {
      try { reg.botaoExpande.focus({ preventScroll: true }); } catch (e) { reg.botaoExpande.focus(); }
    }

    /* Suspensão refeita do zero: só o foco de teclado dentro da faixa a mantém. O
       ponteiro volta a contar no próximo `pointerenter`. */
    Object.keys(carrosseis).forEach(function (k) {
      var c = carrosseis[k];
      var foco = document.activeElement;
      c.suspenso = !!foco && c.caixa.contains(foco) && focoDeTeclado(foco);
      agenda(c);
    });
  }

  /* Os primeiros parágrafos da seção da Metodologia, copiados do painel já montado — o
     mesmo texto, com os mesmos negritos, sem uma segunda leitura do markdown. */
  function resumoDaSecao(ancora) {
    var titulo = ancora && document.getElementById(ancora);
    if (!titulo) return [];
    var saida = [];
    var no = titulo.nextElementSibling;
    while (no && saida.length < PARAGRAFOS_RESUMO && !/^(H[1-4]|SECTION)$/.test(no.tagName)) {
      if (no.tagName === 'P') saida.push(no.cloneNode(true));
      no = no.nextElementSibling;
    }
    return saida;
  }

  function fichaPorSerie() {
    var mapa = {};
    var bloco = (window.MONITOR.metodologia_blocos || []).filter(function (b) {
      return b.tipo === 'ficha';
    })[0];
    if (bloco) bloco.linhas.forEach(function (l) { mapa[l.serie_id] = l; });
    return mapa;
  }

  function mesAno(iso) {
    if (!iso) return '—';
    var p = String(iso).split('-');
    return MESES[parseInt(p[1], 10) - 1] + '/' + p[0];
  }

  /* Refeita a cada desenho do cartão expandido, porque a lista de séries depende do
     período (série sem observação no intervalo sai do gráfico e da lista). Redimensionar,
     trocar o tema ou a chegada da fonte também redesenham, e jogavam o leitor de volta
     ao topo das notas no meio da leitura: a posição da rolagem é guardada e reposta. */
  function preencheNotas(reg) {
    var notas = dialogo.notas;
    var rolagemNotas = notas.scrollTop, rolagemCorpo = dialogo.corpo.scrollTop;
    notas.innerHTML = '';

    var secao = el('section', 'notas__bloco');
    secao.appendChild(el('h3', 'notas__titulo', 'Metodologia'));
    resumoDaSecao(reg.def.metodologia).forEach(function (p) { secao.appendChild(p); });
    if (reg.def.metodologia) {
      var link = el('button', 'notas__link', 'Ler a nota completa na Metodologia');
      link.type = 'button';
      link.addEventListener('click', function () {
        fechaDialogo();
        vaiParaMetodologia(reg.def.metodologia);
      });
      secao.appendChild(link);
    }
    notas.appendChild(secao);

    var base = (window.MONITOR.bases || []).filter(function (b) { return b.id === reg.base; })[0];
    if (base && reg.def.bases.length) {
      var bb = el('section', 'notas__bloco');
      bb.appendChild(el('h3', 'notas__titulo', 'Base exibida: ' + base.rotulo));
      bb.appendChild(el('p', null, base.descricao));
      notas.appendChild(bb);
    }

    var fichas = fichaPorSerie();
    var bs = el('section', 'notas__bloco');
    bs.appendChild(el('h3', 'notas__titulo', 'Séries'));
    var lista = el('dl', 'notas__series');
    reg.seriesVisiveis.forEach(function (s) {
      var f = fichas[s.serie_id] || {};
      lista.appendChild(el('dt', null, s.rotulo));
      var dd = el('dd');
      if (f.nome_oficial) dd.appendChild(el('span', 'notas__nome', f.nome_oficial));
      var origem = [f.fonte || s.fonte, f.codigo].filter(Boolean).join(' ');
      dd.appendChild(el('span', null, origem + (f.tabela ? ' · ' + f.tabela : '')));
      if (f.conversao) dd.appendChild(el('span', null, f.conversao));
      dd.appendChild(el('span', null, mesAno(f.primeira_obs) + ' a ' + mesAno(f.ultima_obs)));
      lista.appendChild(dd);
    });
    bs.appendChild(lista);
    notas.appendChild(bs);
    notas.scrollTop = rolagemNotas;
    dialogo.corpo.scrollTop = rolagemCorpo;
  }

  // ------------------------------------------------------------------ abas

  function controlePeriodoDaAba(abaId) {
    var caixa = el('div', 'painel__periodo');
    caixa.appendChild(el('span', null, 'Período desta aba'));

    var campos = camposIntervalo(function (v) {
      (registros[abaId] || []).forEach(function (r) {
        r.custom = v;
        r.periodoUI.marca('__custom');
        r.campos.caixa.hidden = false;
        r.campos.de.value = v.de ? v.de.slice(0, 7) : '';
        r.campos.ate.value = v.ate ? v.ate.slice(0, 7) : '';
        desenha(r);
      });
    });

    var periodo = seletorPeriodo(window.MONITOR.periodo_padrao, function (id) {
      periodo.marca(id);
      if (id === '__custom') { campos.caixa.hidden = false; return; }
      campos.caixa.hidden = true;
      (registros[abaId] || []).forEach(function (r) {
        r.custom = null;
        r.periodo = id;
        r.periodoUI.marca(id);
        r.campos.caixa.hidden = true;
        desenha(r);
      });
    });

    caixa.appendChild(periodo.elemento);
    caixa.appendChild(campos.caixa);
    return caixa;
  }

  function montaPainel(aba) {
    var painel = el('div', 'painel');
    painel.id = 'painel-' + aba.id;
    painel.hidden = true;
    painel.setAttribute('role', 'tabpanel');
    painel.setAttribute('aria-labelledby', idDaAba(aba.id));

    var cab = el('div', 'painel__cabecalho');
    var intro = el('div', 'painel__intro');
    intro.appendChild(el('h2', 'painel__titulo', aba.titulo));
    if (aba.subtitulo) intro.appendChild(el('p', 'painel__linha', aba.subtitulo));
    cab.appendChild(intro);
    cab.appendChild(controlePeriodoDaAba(aba.id));
    painel.appendChild(cab);

    /* Nenhum desenho aqui. Desenhar sem instância só calcularia uma opção que ninguém
       usa, com largura zero, porque o painel está oculto — todos os gráficos do site
       calculados e jogados fora na abertura. `inicializa`, chamado por `ativa` quando a aba aparece, é quem desenha
       pela primeira vez; até lá o cartão não está na tela, e download e expansão, que
       dependem de `seriesVisiveis` e `opcao`, não são alcançáveis. */
    registros[aba.id] = [];
    aba.graficos.forEach(function (g) {
      registros[aba.id].push(montaCartao(g, aba.id));
    });
    painel.appendChild(montaCarrossel(aba.id, registros[aba.id]));
    return painel;
  }

  function idDaAba(id) { return 'aba-pilula-' + id; }

  var abaAtiva = null;

  /* Gráficos que estão de fato na tela: os já iniciados da aba visível e o do modal, se
     houver. Redimensionar, trocar o tema e a chegada da fonte só redesenham estes; um
     gráfico de aba oculta mediria largura zero, cairia no valor de reserva e ficaria
     errado ao aparecer. Esses são redesenhados por `ativa`, quando a aba é mostrada. */
  function regsNaTela() {
    var lista = (registros[abaAtiva] || []).filter(function (r) { return r.instancia; });
    var doModal = dialogo && dialogo.reg;
    if (doModal && doModal.instancia && lista.indexOf(doModal) < 0) lista.push(doModal);
    return lista;
  }

  function ativa(id) {
    abaAtiva = id;
    Object.keys(paineis).forEach(function (outro) {
      var ativo = outro === id;
      paineis[outro].hidden = !ativo;
      botoesAba[outro].setAttribute('aria-selected', ativo ? 'true' : 'false');
      // Tabindex móvel: só a aba selecionada entra na ordem do Tab; as setas trocam.
      botoesAba[outro].tabIndex = ativo ? 0 : -1;
    });
    /* Gráfico já iniciado é redimensionado E redesenhado: enquanto a aba estava oculta,
       a janela pode ter mudado de largura ou o tema de cor, e nenhum desses eventos
       redesenha aba oculta. O de primeira vez é desenhado por `inicializa`. */
    (registros[id] || []).forEach(function (reg) {
      if (reg.instancia) {
        reg.instancia.resize();
        desenha(reg);
      } else {
        inicializa(reg);
      }
    });
    // Só a faixa da aba visível gira; as outras param onde estavam.
    Object.keys(carrosseis).forEach(function (abaId) {
      var c = carrosseis[abaId];
      c.ativo = abaId === id;
      if (c.ativo) atualizaBarra(c);
      agenda(c);
    });
  }

  // ------------------------------------------------------------------ metodologia

  var ancoras = [];

  /* Rolagem até um elemento, descontando a barra de abas fixa.
   *
   * Não usa `scrollIntoView`: a barra sticky cobriria o título de destino, e a altura
   * dela muda quando as pílulas quebram em duas linhas, então o desconto tem de ser
   * medido e não fixado. A suavidade é pedida aqui, e não por `scroll-behavior` no CSS,
   * para que só esta rolagem seja animada.
   */
  function rolaAte(elemento) {
    var barra = document.querySelector('.abas');
    var folga = (barra ? barra.offsetHeight : 0) + 16;
    var topo = Math.max(0, elemento.getBoundingClientRect().top + window.scrollY - folga);

    if (semMovimento) { window.scrollTo({ top: topo, behavior: 'auto' }); return; }

    var partida = window.scrollY;
    window.scrollTo({ top: topo, behavior: 'smooth' });
    /* Rede de segurança: há contextos em que a rolagem suave não é executada — navegador
       com animações desligadas, automação — e aí o leitor clicaria no "i" e nada
       aconteceria. Se depois de um tempo a página não saiu do lugar, vai direto. Chegar
       sem animação é muito melhor que não chegar. */
    setTimeout(function () {
      if (Math.abs(window.scrollY - partida) < 2 && Math.abs(topo - partida) > 2) {
        window.scrollTo({ top: topo, behavior: 'auto' });
      }
    }, 250);
  }

  function vaiParaMetodologia(ancora) {
    ativa(ID_ABA_METODOLOGIA);
    var alvo = document.getElementById(ancora);
    if (!alvo) return;
    /* Direto, sem esperar quadro nenhum: `getBoundingClientRect`, dentro de `rolaAte`,
       força o layout de forma síncrona, e o painel já foi exibido por `ativa` na linha
       acima. A versão anterior adiava com `requestAnimationFrame` para "deixar o layout
       assentar" — desnecessário, e pior: onde o rAF é estrangulado, o clique no "i" não
       rolava nada. */
    rolaAte(alvo);
    alvo.classList.remove('some');
    alvo.classList.add('destacado');
    setTimeout(function () {
      alvo.classList.add('some');
      setTimeout(function () { alvo.classList.remove('destacado', 'some'); }, 1200);
    }, 1500);
  }

  function escapa(t) {
    return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function enfase(t) {
    return t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>');
  }

  function tituloComAncora(bruto) {
    var m = /^(#{1,4})\s+([\s\S]+)$/.exec(bruto);
    if (!m) return null;
    var texto = m[2].trim(), ancora = null;
    var comId = /^([\s\S]+?)\s*\{#([a-z0-9-]+)\}$/.exec(texto);
    if (comId) { texto = comId[1].trim(); ancora = comId[2]; }
    return { nivel: m[1].length, texto: texto, ancora: ancora };
  }

  function markdown(destino, texto, blocos) {
    var primeiro = true;
    texto.split(/\n\s*\n/).forEach(function (bruto) {
      var trecho = bruto.trim();
      if (!trecho) return;

      if (primeiro) {
        primeiro = false;
        // O `#` de abertura é o título do documento; o painel já desenha um.
        if (/^#\s/.test(trecho)) return;
      }

      var marcador = /^\{\{([a-z_]+)\}\}$/.exec(trecho);
      if (marcador) {
        var bloco = (blocos || []).filter(function (b) { return b.tipo === marcador[1]; })[0];
        if (bloco) destino.appendChild(blocoGerado(bloco));
        return;
      }

      var titulo = tituloComAncora(trecho);
      if (titulo) {
        var h = el('h' + Math.min(titulo.nivel + 1, 4), null, titulo.texto);
        if (titulo.ancora) h.id = titulo.ancora;
        destino.appendChild(h);
        if (titulo.nivel <= 3) {
          ancoras.push({ texto: titulo.texto, nivel: titulo.nivel, elemento: h });
        }
        return;
      }

      if (/^[-*]\s+/.test(trecho)) {
        var itens = [];
        trecho.split(/\n/).forEach(function (linha) {
          var marcado = /^[-*]\s+([\s\S]+)$/.exec(linha.trim());
          if (marcado) itens.push(marcado[1]);
          else if (itens.length) itens[itens.length - 1] += ' ' + linha.trim();
        });
        var ul = document.createElement('ul');
        itens.forEach(function (t) {
          var li = document.createElement('li');
          li.innerHTML = enfase(escapa(t));
          ul.appendChild(li);
        });
        destino.appendChild(ul);
        return;
      }

      var p = document.createElement('p');
      p.innerHTML = enfase(escapa(trecho.replace(/\s*\n\s*/g, ' ')));
      destino.appendChild(p);
    });
  }

  function blocoGerado(bloco) {
    var s = el('section');
    var h = el('h2', null, bloco.titulo);
    h.id = 'bloco-' + bloco.tipo;
    s.appendChild(h);
    ancoras.push({ texto: bloco.titulo, nivel: 2, elemento: h });

    if (bloco.tipo === 'fontes') {
      s.appendChild(el('p', null,
        'Frequência de coleta: ' + bloco.frequencia +
        ' Última atualização em ' + bloco.atualizado_em + ', horário de Brasília.' +
        ' Próxima coleta prevista para ' + dataBr(bloco.proxima_coleta) + '.'));
      var ulf = document.createElement('ul');
      bloco.linhas.forEach(function (l) {
        var li = document.createElement('li');
        li.innerHTML = '<strong>' + escapa(l.fonte) + '</strong> — ' + l.n_series +
          ' séries, observação mais recente em ' + dataBr(l.ultima_obs) + '.';
        ulf.appendChild(li);
      });
      s.appendChild(ulf);
      return s;
    }

    if (bloco.tipo === 'transformacoes') {
      s.appendChild(el('p', null,
        'Mês-base do deflator nesta atualização: ' + (bloco.base_deflator || '—') +
        ', série ' + (bloco.codigo_deflator || '—') + '. Vintage do PIB no denominador: ' +
        (bloco.vintage_pib || '—') + ', série ' + (bloco.codigo_pib || '—') + '. Os dois são ' +
        'móveis e mudam a cada atualização, por isso esta seção é gerada pelo pipeline.'));
      bloco.linhas.forEach(function (l) {
        var d = el('div', 'formula');
        d.appendChild(el('span', 'formula__id', l.rotulo + '  ·  sufixo ' + l.sufixo));
        d.appendChild(document.createTextNode(l.regra));
        s.appendChild(d);
      });
      return s;
    }

    if (bloco.tipo === 'derivadas') {
      s.appendChild(el('p', null,
        'Séries que não existem em fonte nenhuma: são calculadas pelo pipeline a partir ' +
        'das séries coletadas, pela fórmula abaixo. Uma data só entra no resultado quando ' +
        'todas as séries envolvidas têm observação naquela data.'));
      bloco.linhas.forEach(function (l) {
        var d = el('div', 'formula');
        d.appendChild(el('span', 'formula__id', l.serie_id + '  ·  ' + l.operacao + '  ·  ' + l.unidade));
        d.appendChild(document.createTextNode(l.formula.replace(/^calculada:\s*/, '')));
        s.appendChild(d);
      });
      return s;
    }

    if (bloco.tipo === 'ficha') {
      s.appendChild(el('p', null,
        bloco.linhas.length + ' séries. A tabela é gerada do catálogo a cada atualização; ' +
        'nenhuma linha é escrita à mão. A coluna de conversão registra toda mudança de ' +
        'unidade entre o que a fonte publica e o que a página exibe.'));
      var env = el('div', 'tabela-envolucro');
      var tabela = el('table', 'ficha');
      var colunas = [
        ['Série', function (l) { return l.serie_id; }, 'ficha__id'],
        ['Nome na fonte', function (l) { return l.nome_oficial; }],
        ['Fonte', function (l) { return l.fonte; }],
        ['Código', function (l) { return l.codigo; }, 'ficha__id'],
        ['Tabela de origem', function (l) { return l.tabela; }],
        ['Unidade original', function (l) { return l.unidade_origem; }],
        ['Unidade exibida', function (l) { return l.unidade_exibicao; }],
        ['Conversão', function (l) { return l.conversao; }],
        ['Segmento', function (l) { return l.segmento; }],
        ['Primeira obs.', function (l) { return dataBr(l.primeira_obs); }],
        ['Última obs.', function (l) { return dataBr(l.ultima_obs); }],
        ['Obs.', function (l) { return l.n_obs; }],
        ['Gráficos', function (l) { return (l.graficos || []).join(' · '); }]
      ];
      var thead = document.createElement('thead');
      var trh = document.createElement('tr');
      colunas.forEach(function (c) { trh.appendChild(el('th', null, c[0])); });
      thead.appendChild(trh);
      tabela.appendChild(thead);

      var tbody = document.createElement('tbody');
      bloco.linhas.forEach(function (l) {
        var linha = document.createElement('tr');
        // Cada linha é âncora, para o ícone "i" poder apontar direto para uma série.
        linha.id = 'serie-' + l.serie_id;
        colunas.forEach(function (c) {
          var v = c[1](l);
          linha.appendChild(el('td', c[2], v == null || v === '' ? '—' : String(v)));
        });
        tbody.appendChild(linha);
      });
      tabela.appendChild(tbody);
      env.appendChild(tabela);
      s.appendChild(env);
      return s;
    }

    if (bloco.tipo === 'historico') {
      if (!bloco.linhas.length) {
        s.appendChild(el('p', null,
          'Ainda não há histórico registrado: ele começa a ser preenchido na primeira ' +
          'atualização depois desta.'));
        return s;
      }
      s.appendChild(el('p', null,
        'Gerado pelo pipeline comparando o estado de cada série com o da execução anterior. ' +
        '"Revisada" é a série cuja última observação não avançou mas cujo número de ' +
        'observações mudou — a fonte reescreveu o histórico, o que é comportamento normal ' +
        'do Banco Central.'));
      var lista = el('ul', 'historico');
      bloco.linhas.forEach(function (l) {
        var li = document.createElement('li');
        li.appendChild(el('span', 'historico__data', dataBr(l.data)));
        var partes = [];
        if (l.novas.length) partes.push(l.novas.length + ' série(s) nova(s)');
        if (l.avancaram.length) {
          partes.push(l.avancaram.length + ' avançaram, até ' + dataBr(l.avancaram[0].para));
        }
        if (l.revisadas.length) partes.push(l.revisadas.length + ' revisada(s) pela fonte');
        if (l.sumiram.length) partes.push(l.sumiram.length + ' saíram do catálogo');
        li.appendChild(el('span', 'historico__texto', partes.join('; ') + '.'));
        lista.appendChild(li);
      });
      s.appendChild(lista);
      return s;
    }

    return s;
  }

  /* Marca no sumário a seção que está na tela. Sem isso o sumário fixo vira só uma lista
     de links, e o leitor perde a noção de onde está num texto longo. */
  function observaSumario() {
    if (typeof IntersectionObserver === 'undefined') return;
    var obs = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (e) {
        if (!e.isIntersecting) return;
        ancoras.forEach(function (a) {
          if (a.botao) a.botao.setAttribute('aria-current', a.elemento === e.target ? 'true' : 'false');
        });
      });
    }, { rootMargin: '-80px 0px -70% 0px' });
    setTimeout(function () { ancoras.forEach(function (a) { obs.observe(a.elemento); }); }, 0);
  }

  function montaMetodologia(dados) {
    var painel = el('div', 'painel');
    painel.id = 'painel-' + ID_ABA_METODOLOGIA;
    painel.hidden = true;
    painel.setAttribute('role', 'tabpanel');
    painel.setAttribute('aria-labelledby', idDaAba(ID_ABA_METODOLOGIA));

    var grade = el('div', 'metodologia');
    var sumario = el('nav', 'sumario');
    sumario.setAttribute('aria-label', 'Sumário da metodologia');
    var corpo = el('div', 'texto');

    ancoras = [];
    if (!dados.metodologia_texto) {
      corpo.appendChild(el('p', null,
        'content/metodologia.md não foi encontrado. Rode `python src/build_dataset.py`.'));
    } else {
      markdown(corpo, dados.metodologia_texto, dados.metodologia_blocos);
      // Bloco gerado que o texto esqueceu de chamar entra no fim, em vez de sumir.
      var usados = {};
      (dados.metodologia_texto.match(/\{\{([a-z_]+)\}\}/g) || []).forEach(function (m) {
        usados[m.slice(2, -2)] = true;
      });
      (dados.metodologia_blocos || []).forEach(function (b) {
        if (!usados[b.tipo]) corpo.appendChild(blocoGerado(b));
      });
    }

    ancoras.forEach(function (a) {
      var b = el('button', 'sumario__item' + (a.nivel > 2 ? ' sumario__recuo' : ''), a.texto);
      b.type = 'button';
      b.addEventListener('click', function () { rolaAte(a.elemento); });
      a.botao = b;
      sumario.appendChild(b);
    });

    // No celular o sumário vira um <details> no topo, em vez de ocupar meia tela.
    var envolucro = sumario;
    if (window.matchMedia('(max-width: 900px)').matches) {
      envolucro = el('details');
      envolucro.appendChild(el('summary', 'sumario__abertura', 'Sumário'));
      envolucro.appendChild(sumario);
    }

    grade.appendChild(envolucro);
    grade.appendChild(corpo);
    painel.appendChild(grade);
    observaSumario();
    return painel;
  }

  // ------------------------------------------------------------------ montagem

  function monta() {
    var dados = window.MONITOR;
    var nav = document.getElementById('abas-nav');
    var area = document.getElementById('abas-paineis');
    var carregando = document.getElementById('carregando');

    function avisa(texto) {
      var alvo = carregando || area || document.body;
      alvo.textContent = texto;
      alvo.className = 'carregando';
    }

    if (!dados) {
      avisa('Dados não carregados. Rode `python src/build_dataset.py` para gerar docs/dados.js.');
      return;
    }

    /* Se o HTML não tem os elementos que esta versão do script espera, o que está em
       cache é uma versão diferente da outra — foi o que aconteceu em 19/09/2026, quando
       a mudança de estrutura deixou HTML novo e `app.js` antigo convivendo por dez
       minutos e a página saiu em branco. Os estáticos agora levam `?v=<hash>`, o que
       impede essa combinação; isto aqui é a segunda trava, para que o pior caso seja uma
       frase legível em vez de uma tela vazia. */
    var linha = document.getElementById('cabecalho-linha');
    var rodape = document.getElementById('rodape-fonte');
    if (!nav || !area || !linha || !rodape) {
      avisa('A página precisa ser recarregada para atualizar (Ctrl+F5).');
      return;
    }

    linha.textContent =
      'Famílias e empresas não financeiras — crédito, inadimplência e dívida. ' +
      'Atualizado em ' + dados.atualizado_em + '.';

    rodape.textContent =
      'Fonte: BCB/SGS e BIS. Última atualização em ' + dados.atualizado_em + '. Ver Metodologia.';

    if (dados.desatualizadas.length) {
      var aviso = document.getElementById('aviso-global');
      aviso.hidden = false;
      aviso.textContent = dados.desatualizadas.length +
        ' série(s) sem atualização na última coleta; os valores exibidos vêm do cache anterior: ' +
        dados.desatualizadas.join(', ') + '.';
    }

    nav.innerHTML = '';
    area.innerHTML = '';
    registros = {}; botoesAba = {}; paineis = {}; instancias = [];
    Object.keys(carrosseis).forEach(function (k) { clearTimeout(carrosseis[k].temporizador); });
    carrosseis = {};

    /* As pílulas são um tablist de verdade: cada aba aponta para o seu painel e é
       nomeada por ele, e as setas esquerda/direita (mais Home e End) andam entre elas,
       ativando a que recebe o foco. */
    nav.setAttribute('role', 'tablist');
    var ordemAbas = [];
    function registra(id, titulo, painel) {
      var b = el('button', 'aba-pilula', titulo);
      b.type = 'button';
      b.id = idDaAba(id);
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', 'false');
      b.setAttribute('aria-controls', painel.id);
      b.tabIndex = -1;
      b.addEventListener('click', function () { ativa(id); });
      nav.appendChild(b);
      botoesAba[id] = b;
      ordemAbas.push(id);
      area.appendChild(painel);
      paineis[id] = painel;
    }

    dados.abas.forEach(function (aba) { registra(aba.id, aba.titulo, montaPainel(aba)); });
    registra(ID_ABA_METODOLOGIA, 'Metodologia', montaMetodologia(dados));
    if (!dialogo) montaDialogo();

    nav.addEventListener('keydown', function (ev) {
      var atual = ordemAbas.indexOf(abaAtiva);
      var n = ordemAbas.length, alvo = null;
      if (ev.key === 'ArrowRight') alvo = (atual + 1) % n;
      else if (ev.key === 'ArrowLeft') alvo = (atual - 1 + n) % n;
      else if (ev.key === 'Home') alvo = 0;
      else if (ev.key === 'End') alvo = n - 1;
      if (alvo === null || atual < 0) return;
      ev.preventDefault();
      ativa(ordemAbas[alvo]);
      botoesAba[ordemAbas[alvo]].focus();
    });

    /* Redimensionar muda a largura do cartão e, com ela, a folga do rótulo de ponta.
       `resize()` sozinho manteria a folga antiga. O debounce existe porque redesenhar
       onze gráficos a cada pixel de arrasto trava a janela.

       Três cortes de custo. Evento em que a LARGURA não mudou é ignorado: no celular a
       barra de endereço some e volta a cada rolagem e dispara `resize` só de altura, e
       os cartões têm altura fixa. A exceção é o modal, cuja altura acompanha a janela —
       ali basta um `resize()` da instância, sem redesenho, porque a folga depende só da
       largura. Os `resize()` de instância saem num único quadro de animação, não um por
       evento. E só os gráficos na tela entram: os de aba oculta são refeitos por `ativa`
       quando a aba aparece. */
    var temporizador = null, quadroResize = null;
    var larguraJanela = window.innerWidth;
    function redimensionaNaTela() {
      if (quadroResize) return;
      quadroResize = requestAnimationFrame(function () {
        quadroResize = null;
        regsNaTela().forEach(function (reg) { reg.instancia.resize(); });
      });
    }
    window.addEventListener('resize', function () {
      if (window.innerWidth === larguraJanela) {
        if (dialogo && dialogo.reg && dialogo.reg.instancia) {
          var doModal = dialogo.reg;
          requestAnimationFrame(function () { if (doModal.instancia) doModal.instancia.resize(); });
        }
        return;
      }
      larguraJanela = window.innerWidth;
      redimensionaNaTela();
      clearTimeout(temporizador);
      temporizador = setTimeout(function () {
        regsNaTela().forEach(desenha);
        /* A largura dos cartões mudou, e com ela o passo da faixa — e, ao cruzar o
           limite do celular, quantos cabem por tela. Volta ao cartão em que estava. */
        Object.keys(carrosseis).forEach(function (abaId) {
          var c = carrosseis[abaId];
          if (!c.ativo) return;
          vaiPara(c, c.indice, false);
          atualizaBarra(c);
          agenda(c);
        });
      }, 180);
    });

    // Aba do navegador em segundo plano: a rotação para e retoma ao voltar.
    document.addEventListener('visibilitychange', function () {
      Object.keys(carrosseis).forEach(function (abaId) { agenda(carrosseis[abaId]); });
    });

    /* O modo escuro troca todos os tokens sem recarregar a página. Os gráficos guardam
       as cores na opção do ECharts, então precisam ser redesenhados na troca. */
    var escuro = window.matchMedia('(prefers-color-scheme: dark)');
    /* Só os da tela: os de aba oculta pegam o tema novo quando `ativa` os redesenha. */
    var aoTrocarTema = function () { regsNaTela().forEach(desenha); };
    if (escuro.addEventListener) escuro.addEventListener('change', aoTrocarTema);
    else if (escuro.addListener) escuro.addListener(aoTrocarTema);

    /* A folga do rótulo de ponta é medida com a fonte de verdade — mas a Hanken Grotesk
       chega do Google Fonts com `display=swap`, quase sempre DEPOIS do primeiro desenho.
       A medida feita com a fonte de reserva fica estreita ou larga demais para o texto
       que o navegador acaba desenhando. Quando as fontes terminam de carregar, os
       gráficos na tela são refeitos com a medida certa. Sem rede, ou por file:// sem as
       fontes, `ready` resolve do mesmo jeito e o redesenho só repete o que já estava. */
    if (document.fonts && document.fonts.ready) {
      var quadroFonte = null;
      var aoCarregarFonte = function () {
        if (quadroFonte) return;
        quadroFonte = requestAnimationFrame(function () {
          quadroFonte = null;
          regsNaTela().forEach(desenha);
        });
      };
      document.fonts.ready.then(aoCarregarFonte, function () {});
      if (document.fonts.addEventListener) {
        document.fonts.addEventListener('loadingdone', aoCarregarFonte);
      }
    }

    if (dados.abas.length) ativa(dados.abas[0].id);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', monta);
  } else {
    monta();
  }
})();
