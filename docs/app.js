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

  function casasDecimais(unidade) {
    if (!unidade) return 2;
    return unidade.indexOf('R$') >= 0 ? 1 : 2;
  }

  function numero(valor, unidade) {
    var casas = casasDecimais(unidade);
    return valor.toLocaleString('pt-BR', {
      minimumFractionDigits: casas, maximumFractionDigits: casas
    });
  }

  /* No eixo e no rótulo de ponta a precisão cheia vira ruído: 50,00 não diz mais que 50.
     O tooltip e o CSV seguem com o valor como o pipeline o calculou. */
  function numeroCurto(valor) {
    return valor.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 1 });
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

  /* Unidade curta para o topo do eixo. O rótulo longo ("R$ bilhões de ago/2026") não
     cabe ali e repete o que o tooltip já diz.

     O acumulado em 12 meses é a exceção que precisa de caso próprio, e vem ANTES do teste
     genérico de "R$": um fluxo mensal e a sua soma de doze meses têm a mesma unidade e
     ordens de grandeza diferentes — R$ 737 bi contra R$ 8.375 bi no mesmo eixo "R$ bi".
     Sem a marca no eixo, a única pista de que a escala mudou seria o seletor. */
  function unidadeCurta(unidade) {
    if (!unidade) return '';
    if (unidade.indexOf('acumulados em 12 meses') >= 0) return 'R$ bi, 12m';
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
    var rotuloMenor = series.length > 5;

    /* Texto de cada rótulo de ponta, e a folga que ele exige.
     *
     * Três formas, na ordem de preferência, escolhidas pela largura disponível:
     *
     *   uma linha    "Total  7.372", o ideal — é o formato que a orientação pede
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
      return { id: s.serie_id, nome: s.rotulo, valor: numeroCurto(ultimo[1]) };
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
        extraCssText: 'box-shadow: 0 8px 24px -16px rgba(0,0,0,.4);',
        // Crosshair vertical fino seguindo o mouse.
        axisPointer: { type: 'line', lineStyle: { color: tk.ink3, width: 1, type: 'solid' } },
        formatter: function (ps) {
          var iso = new Date(ps[0].value[0]).toISOString().slice(0, 10);
          var html = '<div class="tt__data">' + rotuloData(iso, periodicidade) + '</div>';
          ps.forEach(function (p) {
            var ref = nominais[p.seriesName];
            var extra = (ref && ref.mapa[iso] !== undefined)
              ? '<span class="tt__ref">de ' + numero(ref.mapa[iso], ref.unidade) + '</span>'
              : '';
            html += '<div class="tt__linha">'
              + '<span class="tt__marca" style="background:' + p.color + '"></span>'
              + '<span class="tt__nome">' + p.seriesName + '</span>'
              + extra
              + '<span class="tt__valor">' + numero(p.value[1], unidade) + '</span>'
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
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: tk.ink3, fontSize: 12, fontFamily: tk.fTexto, hideOverlap: true }
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
        axisLabel: { color: tk.ink3, fontSize: 12, fontFamily: tk.fTexto, formatter: numeroCurto }
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
    var base = (window.MONITOR.bases || []).filter(function (b) { return b.id === reg.base; })[0];
    var sufixo = base ? base.sufixo : '';

    var linhas = [['data'].concat(series.map(function (s) { return s.serie_id + sufixo; })).join(';')];
    ordenadas.forEach(function (d) {
      linhas.push([d].concat(indices.map(function (m) {
        return m[d] === undefined ? '' : String(m[d]);
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
  function png(reg) {
    if (!reg.instancia) return;
    var tk = tokens();
    var url = reg.instancia.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: tk.surface });
    var img = new Image();
    img.onload = function () {
      var topo = 64, base = 48, margem = 32;
      var cv = document.createElement('canvas');
      cv.width = img.width;
      cv.height = img.height + topo + base;
      var ctx = cv.getContext('2d');
      ctx.fillStyle = tk.surface;
      ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.drawImage(img, 0, topo);
      ctx.textBaseline = 'middle';

      ctx.fillStyle = tk.ink;
      ctx.font = '500 32px ' + tk.fTexto;
      ctx.fillText(reg.def.titulo, margem, topo / 2);

      ctx.fillStyle = tk.ink3;
      ctx.font = '400 24px ' + tk.fTexto;
      ctx.fillText(
        'Fonte: ' + fonteDe(reg.seriesVisiveis) + ' · Monitor de Crédito e Endividamento',
        margem, img.height + topo + base / 2
      );
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

  function iconeInfo(grafico) {
    if (!grafico.metodologia) return null;
    var b = el('button', 'info', 'i');
    b.type = 'button';
    b.title = 'Nota metodológica';
    b.setAttribute('aria-label', 'Nota metodológica de ' + grafico.titulo);
    b.addEventListener('click', function () { vaiParaMetodologia(grafico.metodologia); });
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
    }
    function foraDaqui(ev) { if (!caixa.contains(ev.target)) fecha(); }
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
      if (abrir) document.addEventListener('click', foraDaqui, true);
    });

    caixa.appendChild(botao);
    caixa.appendChild(menu);
    return caixa;
  }

  // ------------------------------------------------------------------ cartão

  function montaCartao(grafico, abaId) {
    var cartao = el('section', 'cartao');
    var largura = grafico.largura || 12;
    cartao.style.setProperty('--col', String(largura));
    cartao.dataset.largura = String(largura);

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

    var info = iconeInfo(grafico);
    if (info) controles.appendChild(info);
    controles.appendChild(menuDownload(reg));

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

  /* As larguras vêm do catálogo em frações de doze. Quando a soma de uma linha não fecha
     — porque o próximo cartão é largo demais para o que sobrou, ou porque um gráfico não
     foi montado —, o último cartão da linha é esticado para não deixar buraco. */
  function ajustaGrade(abaId) {
    var linha = [], usado = 0;
    function aplica(cartao, col) {
      cartao.style.setProperty('--col', String(col));
      // A coluna EFETIVA, já contando o estica. É por ela que o CSS decide empilhar os
      // controles e escolher a altura — `data-largura` guarda só o que o catálogo pediu.
      cartao.dataset.col = String(col);
    }
    function fecha() {
      if (!linha.length) return;
      var ultimo = linha[linha.length - 1];
      var declarado = parseInt(ultimo.cartao.dataset.largura, 10);
      aplica(ultimo.cartao, declarado + (12 - usado));
    }
    (registros[abaId] || []).forEach(function (reg) {
      var w = parseInt(reg.cartao.dataset.largura, 10);
      aplica(reg.cartao, w);
      if (usado + w > 12) { fecha(); linha = []; usado = 0; }
      linha.push(reg);
      usado += w;
      if (usado === 12) { linha = []; usado = 0; }
    });
    fecha();
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

    var cab = el('div', 'painel__cabecalho');
    var intro = el('div', 'painel__intro');
    intro.appendChild(el('h2', 'painel__titulo', aba.titulo));
    if (aba.subtitulo) intro.appendChild(el('p', 'painel__linha', aba.subtitulo));
    cab.appendChild(intro);
    cab.appendChild(controlePeriodoDaAba(aba.id));
    painel.appendChild(cab);

    var grade = el('div', 'grade');
    registros[aba.id] = [];
    aba.graficos.forEach(function (g) {
      var reg = montaCartao(g, aba.id);
      grade.appendChild(reg.cartao);
      registros[aba.id].push(reg);
      desenha(reg);
    });
    painel.appendChild(grade);
    ajustaGrade(aba.id);
    return painel;
  }

  function ativa(id) {
    Object.keys(paineis).forEach(function (outro) {
      var ativo = outro === id;
      paineis[outro].hidden = !ativo;
      botoesAba[outro].setAttribute('aria-selected', ativo ? 'true' : 'false');
    });
    (registros[id] || []).forEach(function (reg) {
      inicializa(reg);
      if (reg.instancia) reg.instancia.resize();
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
      'Fonte: BCB/SGS e FRED. Última atualização em ' + dados.atualizado_em + '. Ver Metodologia.';

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

    function registra(id, titulo, painel) {
      var b = el('button', 'aba-pilula', titulo);
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', 'false');
      b.addEventListener('click', function () { ativa(id); });
      nav.appendChild(b);
      botoesAba[id] = b;
      area.appendChild(painel);
      paineis[id] = painel;
    }

    dados.abas.forEach(function (aba) { registra(aba.id, aba.titulo, montaPainel(aba)); });
    registra(ID_ABA_METODOLOGIA, 'Metodologia', montaMetodologia(dados));

    /* Redimensionar muda a largura do cartão e, com ela, a folga do rótulo de ponta.
       `resize()` sozinho manteria a folga antiga. O debounce existe porque redesenhar
       onze gráficos a cada pixel de arrasto trava a janela. */
    var temporizador = null;
    window.addEventListener('resize', function () {
      instancias.forEach(function (i) { i.resize(); });
      clearTimeout(temporizador);
      temporizador = setTimeout(function () {
        Object.keys(registros).forEach(function (abaId) {
          registros[abaId].forEach(function (reg) { if (reg.instancia) desenha(reg); });
        });
      }, 180);
    });

    /* O modo escuro troca todos os tokens sem recarregar a página. Os gráficos guardam
       as cores na opção do ECharts, então precisam ser redesenhados na troca. */
    var escuro = window.matchMedia('(prefers-color-scheme: dark)');
    var aoTrocarTema = function () {
      Object.keys(registros).forEach(function (abaId) {
        registros[abaId].forEach(desenha);
      });
    };
    if (escuro.addEventListener) escuro.addEventListener('change', aoTrocarTema);
    else if (escuro.addListener) escuro.addListener(aoTrocarTema);

    if (dados.abas.length) ativa(dados.abas[0].id);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', monta);
  } else {
    monta();
  }
})();
