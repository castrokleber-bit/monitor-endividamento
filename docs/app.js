/* Monitor de Endividamento — montagem da página.
 *
 * Sem build step: lê `window.MONITOR`, gerado por src/build_dataset.py e carregado por
 * dados.js. O payload vem embutido num <script> justamente para que a página funcione
 * tanto por file:// quanto servida no GitHub Pages, com o mesmo código.
 *
 * Este arquivo não interpreta dado: não calcula, não completa lacuna, não arredonda
 * valor armazenado. Só formata para exibição.
 *
 * Cor sai exclusivamente das custom properties de style.css. Nenhum hex aqui.
 */
(function () {
  'use strict';

  var MESES_TRI = { 1: '1º tri', 4: '2º tri', 7: '3º tri', 10: '4º tri' };

  // Cópia que build_xlsx.py deixa em docs/. O original versionado fica em data/.
  var ARQUIVO_XLSX = 'monitor_endividamento.xlsx';

  var raiz = getComputedStyle(document.documentElement);
  function token(nome) {
    return raiz.getPropertyValue(nome).trim();
  }

  var PALETA = ['--serie-1', '--serie-2', '--serie-3', '--serie-4', '--serie-5'].map(token);
  var COR_TEXTO = token('--cinza');
  var COR_GRID = token('--cinza-claro');
  var COR_FUNDO = token('--fundo');

  var semAnimacao = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ------------------------------------------------------------------ formatação

  function casasDecimais(unidade) {
    // Regra fixa de exibição — não altera o valor armazenado.
    return unidade && unidade.indexOf('R$') >= 0 ? 0 : 2;
  }

  function numero(valor, unidade) {
    return valor.toLocaleString('pt-BR', {
      minimumFractionDigits: casasDecimais(unidade),
      maximumFractionDigits: casasDecimais(unidade)
    });
  }

  /* No eixo a precisão cheia vira ruído: 50,00 não diz mais que 50. O tooltip e o CSV
     seguem com o valor como veio da fonte. */
  function numeroEixo(valor, unidade) {
    return valor.toLocaleString('pt-BR', {
      minimumFractionDigits: 0,
      maximumFractionDigits: casasDecimais(unidade) === 0 ? 0 : 1
    });
  }

  function partesData(iso) {
    var p = iso.split('-');
    return { ano: p[0], mes: parseInt(p[1], 10) };
  }

  function rotuloData(iso, periodicidade) {
    var d = partesData(iso);
    if (periodicidade === 'A') return d.ano;
    if (periodicidade === 'T') return (MESES_TRI[d.mes] || d.mes) + '/' + d.ano;
    return String(d.mes).padStart(2, '0') + '/' + d.ano;
  }

  function elemento(tag, classe, texto) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (texto != null) el.textContent = texto;
    return el;
  }

  /* Markdown mínimo para os textos humanos de content/: títulos, parágrafos, **forte**
     e *ênfase*. Nada além disso — o conteúdo é escrito por pessoas, não gerado, e o
     front transporta em vez de interpretar.

     O HTML é escapado ANTES de aplicar ênfase, então nada que venha do arquivo vira
     marcação. */
  function escapaHtml(texto) {
    return texto
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function enfase(texto) {
    return texto
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      // Códigos de série e caminhos de arquivo vêm entre crases no markdown; sem esta
      // regra as crases apareciam cruas na página.
      .replace(/`(.+?)`/g, '<code>$1</code>');
  }

  function markdown(destino, texto, classeParagrafo, nivelBase) {
    var base = nivelBase || 3;
    texto.split(/\n\s*\n/).forEach(function (bruto) {
      var trecho = bruto.trim();
      if (!trecho) return;

      var titulo = /^(#{1,4})\s+([\s\S]+)$/.exec(trecho);
      if (titulo) {
        var nivel = Math.min(base + titulo[1].length - 1, 6);
        destino.appendChild(elemento('h' + nivel, null, titulo[2].trim()));
        return;
      }

      var p = elemento('p', classeParagrafo);
      // Quebra simples dentro do parágrafo não vira <br>: o texto é corrido.
      p.innerHTML = enfase(escapaHtml(trecho.replace(/\s*\n\s*/g, ' ')));
      destino.appendChild(p);
    });
  }

  // ------------------------------------------------------------------ gráfico

  /* Recorte de exibição, vindo de config/blocos.yaml. Corta o que o gráfico e o CSV do
     gráfico mostram — nunca o que está em data/ ou na planilha, que seguem inteiros. */
  function recorta(serie, corte) {
    if (!corte) return serie.obs;
    return serie.obs.filter(function (o) { return o[0] >= corte; });
  }

  function opcoes(grafico, series) {
    var unidade = grafico.unidade;
    var periodicidade = series[0].periodicidade;

    return {
      // As datas são o primeiro dia do período em UTC. Sem isto o ECharts converteria
      // para o fuso local e 01/06 apareceria como 31/05 no eixo.
      useUTC: true,
      animation: !semAnimacao,
      backgroundColor: COR_FUNDO,
      color: PALETA,
      /* `containLabel` dimensiona a margem pelo rótulo real do eixo. Margem fixa cortava
         valores longos, como os saldos em R$ milhões na casa dos milhões.

         A folga inferior cresce com o número de séries porque, na metade da largura da
         página, a legenda de três ou quatro séries quebra em duas linhas e encostava na
         área do gráfico. */
      grid: {
        left: 4,
        right: 16,
        top: 24,
        bottom: series.length > 2 ? 54 : (series.length > 1 ? 32 : 8),
        containLabel: true
      },
      legend: series.length > 1
        ? { bottom: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 8,
            textStyle: { color: COR_TEXTO, fontFamily: 'Arial, Helvetica, sans-serif' } }
        : undefined,
      tooltip: {
        trigger: 'axis',
        backgroundColor: COR_FUNDO,
        borderColor: COR_GRID,
        textStyle: { color: COR_TEXTO, fontFamily: 'Arial, Helvetica, sans-serif' },
        formatter: function (pontos) {
          var iso = new Date(pontos[0].value[0]).toISOString().slice(0, 10);
          var linhas = [rotuloData(iso, periodicidade)];
          pontos.forEach(function (ponto) {
            linhas.push(ponto.marker + ponto.seriesName + ': ' +
              numero(ponto.value[1], unidade) + ' ' + unidade);
          });
          return linhas.join('<br>');
        }
      },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: COR_GRID } },
        axisTick: { lineStyle: { color: COR_GRID } },
        axisLabel: { color: COR_TEXTO, fontFamily: 'Arial, Helvetica, sans-serif' }
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLine: { show: false },
        splitLine: { lineStyle: { color: COR_GRID } },
        axisLabel: {
          color: COR_TEXTO,
          fontFamily: 'Arial, Helvetica, sans-serif',
          formatter: function (v) { return numeroEixo(v, unidade); }
        }
      },
      series: series.map(function (s) {
        return {
          name: s.rotulo,
          type: 'line',
          showSymbol: false,
          symbol: 'circle',
          lineStyle: { width: 2 },
          emphasis: { focus: 'series' },
          data: s.visivel.map(function (o) { return [o[0], o[1]]; })
        };
      })
    };
  }

  // ------------------------------------------------------------------ download

  function csv(grafico, series, corte) {
    var datas = {};
    series.forEach(function (s) {
      s.visivel.forEach(function (o) { datas[o[0]] = true; });
    });
    var ordenadas = Object.keys(datas).sort();

    var indices = series.map(function (s) {
      var mapa = {};
      s.visivel.forEach(function (o) { mapa[o[0]] = o[1]; });
      return mapa;
    });

    var linhas = [['data'].concat(series.map(function (s) { return s.serie_id; })).join(';')];
    ordenadas.forEach(function (data) {
      linhas.push([data].concat(indices.map(function (mapa) {
        // Ponto decimal e campo vazio para lacuna — nada é preenchido.
        return mapa[data] === undefined ? '' : String(mapa[data]);
      })).join(';'));
    });

    var cabecalho = [
      '# ' + grafico.titulo,
      '# unidade: ' + grafico.unidade,
      '# fonte: ' + grafico.fonte,
      '# gerado do Monitor de Endividamento, dados de ' + window.MONITOR.gerado_em
    ];
    if (corte) {
      cabecalho.push(
        '# recorte do painel: a partir de ' + corte +
        '. A série completa está na planilha XLSX.'
      );
    }
    cabecalho = cabecalho.join('\n');

    return cabecalho + '\n' + linhas.join('\n') + '\n';
  }

  function baixar(nome, conteudo) {
    // BOM para o Excel abrir o CSV em UTF-8 sem estragar os acentos.
    var blob = new Blob(['﻿' + conteudo], { type: 'text/csv;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = nome;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function nomeArquivo(titulo) {
    return titulo
      .toLowerCase()
      .normalize('NFD')
      // remove as marcas combinantes soltas pelo NFD (U+0300–U+036F)
      .replace(new RegExp('[\\u0300-\\u036f]', 'g'), '')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '') + '.csv';
  }

  // ------------------------------------------------------------------ montagem

  /* Gráficos pendentes de inicialização. O ECharts mede o elemento no init, então só
     pode rodar depois que o cartão estiver no documento — senão a largura é zero. */
  var pendentes = [];

  function montaGrafico(grafico, dados) {
    var series = grafico.series.map(function (id) {
      var serie = Object.assign({ serie_id: id }, dados.series[id]);
      // `rotulos` no gráfico sobrescreve o rótulo do catálogo — necessário quando o
      // mesmo rótulo se repetiria na legenda (três séries do Brasil, por exemplo).
      if (grafico.rotulos && grafico.rotulos[id]) serie.rotulo = grafico.rotulos[id];
      return serie;
    });

    // `inicio` do próprio gráfico sobrescreve o recorte geral de blocos.yaml.
    var corte = grafico.inicio || (dados.recorte && dados.recorte.inicio) || null;
    series.forEach(function (s) { s.visivel = recorta(s, corte); });

    var cortou = series.some(function (s) { return s.visivel.length < s.obs.length; });
    var pontos = series.reduce(function (todos, s) { return todos.concat(s.visivel); }, []);

    if (!pontos.length) {
      // Recorte posterior ao fim de todas as séries do gráfico: melhor mostrar a série
      // inteira do que um gráfico vazio.
      series.forEach(function (s) { s.visivel = s.obs; });
      cortou = false;
      pontos = series.reduce(function (todos, s) { return todos.concat(s.visivel); }, []);
    }

    var cartao = elemento('section', 'grafico');
    cartao.appendChild(elemento('h2', null, grafico.titulo));

    var inicio = pontos.reduce(function (menor, o) {
      return o[0] < menor ? o[0] : menor;
    }, pontos[0][0]);
    var fim = pontos.reduce(function (maior, o) {
      return o[0] > maior ? o[0] : maior;
    }, pontos[0][0]);

    cartao.appendChild(elemento(
      'p', 'grafico__subtitulo',
      grafico.unidade + ' — ' +
      rotuloData(inicio, series[0].periodicidade) + ' a ' +
      rotuloData(fim, series[0].periodicidade)
    ));

    /* A ressalva metodológica vem antes do gráfico: tem de ser lida junto com a curva,
       não depois dela.

       O vão é criado mesmo sem nota, e sempre na mesma posição, para que todo cartão
       tenha o mesmo número de filhos. É disso que depende o alinhamento por `subgrid`
       de style.css: sem o vão, o cartão com nota empurraria o próprio gráfico para
       baixo e as duas curvas de uma mesma linha ficariam em alturas diferentes. */
    var vaoNota = elemento('div', 'grafico__nota');
    if (grafico.nota) vaoNota.appendChild(elemento('p', 'nota nota--grafico', grafico.nota));
    cartao.appendChild(vaoNota);

    var area = elemento('div', 'grafico__area');
    cartao.appendChild(area);

    var meta = elemento('div', 'grafico__meta');
    meta.appendChild(elemento('div', null, 'Fonte: ' + grafico.fonte + '.'));

    if (cortou) {
      meta.appendChild(elemento(
        'div', null,
        'Gráfico recortado a partir de ' + corte.slice(0, 4) +
        '. As séries completas, desde a primeira observação de cada fonte, estão na ' +
        'planilha XLSX.'
      ));
    }

    series.forEach(function (s) {
      /* Série derivada traz `calculo` e não vem pronta de fonte nenhuma: a linha de
         procedência diz como foi calculada, para o leitor não tomar valor computado
         aqui por valor divulgado pelo BCB. */
      var origem = s.calculo
        ? s.rotulo + ' — ' + s.calculo + '. '
        : s.rotulo + ' — código ' + s.codigo_fonte + ' (' + s.fonte + '), série da fonte com ';
      meta.appendChild(elemento(
        'div', null,
        origem + s.n_obs + ' observações desde ' +
        rotuloData(s.inicio, s.periodicidade) + ', última em ' +
        rotuloData(s.ultima_data, s.periodicidade) + '.'
      ));
      if (s.nota) meta.appendChild(elemento('div', 'nota', s.nota));
      if (s.status === 'stale') {
        meta.appendChild(elemento(
          'div', 'aviso-desatualizado',
          'Série desatualizada: a fonte não respondeu na última coleta e o valor exibido ' +
          'vem do cache anterior.'
        ));
      }
    });

    var acoes = elemento('div', 'grafico__acoes');

    /* Caminho relativo a docs/, não a data/: o GitHub Pages publica apenas docs/, e
       build_xlsx.py deixa uma cópia da planilha aqui exatamente por isso. Assim o mesmo
       href funciona por file:// e no site. */
    var planilha = elemento('a', 'baixar', 'Baixar todas as séries (XLSX)');
    planilha.href = ARQUIVO_XLSX;
    planilha.setAttribute('download', '');
    acoes.appendChild(planilha);

    var botao = elemento('button', 'baixar', 'Baixar este gráfico (CSV)');
    botao.type = 'button';
    botao.addEventListener('click', function () {
      baixar(nomeArquivo(grafico.titulo), csv(grafico, series, cortou ? corte : null));
    });
    acoes.appendChild(botao);

    meta.appendChild(acoes);

    cartao.appendChild(meta);
    pendentes.push({ area: area, opcao: opcoes(grafico, series) });

    return cartao;
  }

  function desenhaPendentes() {
    if (typeof echarts === 'undefined') {
      // O ECharts vem de CDN. Sem rede, o resto da página (números, fontes, downloads)
      // continua utilizável — só os gráficos não desenham.
      pendentes.forEach(function (p) {
        p.area.className = 'carregando';
        p.area.textContent =
          'Gráfico indisponível: a biblioteca ECharts não carregou (sem conexão). ' +
          'Os dados continuam disponíveis no botão de download.';
      });
      pendentes = [];
      return;
    }

    var instancias = pendentes.map(function (p) {
      var instancia = echarts.init(p.area, null, { renderer: 'svg' });
      instancia.setOption(p.opcao);
      return instancia;
    });
    pendentes = [];

    window.addEventListener('resize', function () {
      instancias.forEach(function (i) { i.resize(); });
    });
  }

  function montaBloco(bloco, dados) {
    var secao = elemento('section', 'bloco');
    secao.id = bloco.id;
    secao.appendChild(elemento('h1', null, bloco.titulo));
    if (bloco.subtitulo) secao.appendChild(elemento('p', 'bloco__subtitulo', bloco.subtitulo));
    if (bloco.nota_metodologica) {
      secao.appendChild(elemento('p', 'nota nota--bloco', bloco.nota_metodologica));
    }

    /* Os cartões vão numa grade de duas colunas, não empilhados: em telas largas cabem
       dois gráficos por linha e a página encurta pela metade. Quem decide a largura é o
       CSS — um gráfico sozinho na última linha ocupa as duas colunas, para não deixar
       meia linha vazia. */
    var grade = elemento('div', 'bloco__graficos');
    bloco.graficos.forEach(function (grafico) {
      grade.appendChild(montaGrafico(grafico, dados));
    });
    secao.appendChild(grade);

    return secao;
  }

  function monta() {
    var dados = window.MONITOR;
    var alvo = document.getElementById('blocos');

    if (!dados) {
      document.getElementById('carregando').textContent =
        'Dados não carregados. Rode `python src/build_dataset.py` para gerar docs/dados.js.';
      return;
    }

    /* `atualizado_em` vem pronto de build_dataset.py, no horário de Brasília. Formatar
       aqui exigiria converter fuso no navegador, e a data da atualização passaria a
       depender do relógio de quem lê. */
    document.getElementById('atualizacao').textContent =
      'Página atualizada em ' +
      (dados.atualizado_em || dados.gerado_em.slice(0, 10).split('-').reverse().join('/')) +
      ' (horário de Brasília) · ' + Object.keys(dados.series).length + ' séries.';

    if (dados.desatualizadas.length) {
      var aviso = document.getElementById('aviso-global');
      aviso.hidden = false;
      aviso.textContent =
        dados.desatualizadas.length + ' série(s) sem atualização na última coleta — ' +
        'os valores exibidos vêm do cache anterior: ' + dados.desatualizadas.join(', ') + '.';
    }

    alvo.innerHTML = '';
    dados.blocos.forEach(function (bloco) {
      alvo.appendChild(montaBloco(bloco, dados));
    });
    montaMetodologia(dados);
    desenhaPendentes();
  }

  /* content/metodologia.md renderizado na própria página, não só linkado: a abrangência
     das fontes é o que sustenta a leitura dos gráficos e não pode depender de o leitor
     abrir outro arquivo. */
  function montaMetodologia(dados) {
    var alvo = document.getElementById('metodologia');
    if (!alvo) return;
    if (!dados.metodologia) {
      alvo.hidden = true;
      return;
    }
    alvo.innerHTML = '';
    markdown(alvo, dados.metodologia, 'metodologia__p', 2);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', monta);
  } else {
    monta();
  }
})();
