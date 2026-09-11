/* Monitor de Endividamento — montagem da página.
 *
 * Sem build step: lê `window.MONITOR`, gerado por src/build_dataset.py e carregado por
 * dados.js. O payload vem embutido num <script> justamente para que a página funcione
 * tanto por file:// quanto servida no GitHub Pages, com o mesmo código.
 *
 * Este arquivo não interpreta dado: não calcula, não completa lacuna, não arredonda
 * valor armazenado. Só formata para exibição, e filtra por segmento (família/empresa)
 * a partir de um campo que já vem pronto no payload — nunca reclassifica.
 *
 * Cor sai exclusivamente das custom properties de style.css. Nenhum hex aqui.
 */
(function () {
  'use strict';

  var MESES_TRI = { 1: '1º tri', 4: '2º tri', 7: '3º tri', 10: '4º tri' };

  // Cópia que build_xlsx.py deixa em docs/. O original versionado fica em data/.
  var ARQUIVO_XLSX = 'monitor_endividamento.xlsx';

  var SEGMENTOS = [
    { id: 'familia', rotulo: 'Família' },
    { id: 'empresa', rotulo: 'Empresas' },
    { id: 'ambos', rotulo: 'Ambos' }
  ];
  var SEGMENTO_PADRAO = 'ambos';

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

  /* Recorte de exibição, vindo de config/abas.yaml. Corta o que o gráfico e o CSV do
     gráfico mostram — nunca o que está em data/ ou na planilha, que seguem inteiros. */
  function recorta(serie, corte) {
    if (!corte) return serie.obs;
    return serie.obs.filter(function (o) { return o[0] >= corte; });
  }

  /* Uma série entra no filtro quando o segmento escolhido bate com o dela, quando o
     filtro está em "Ambos" (mostra tudo) ou quando a própria série é "ambos" — um
     total ou agregado que faz sentido como referência nos dois filtros específicos. */
  function serieNoFiltro(serie, segmento) {
    return segmento === 'ambos' || serie.segmento === segmento || serie.segmento === 'ambos';
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

  // ------------------------------------------------------------------ estado das abas

  /* Um registro por gráfico, vivo enquanto a página existe. Guarda o que muda quando o
     filtro de segmento troca (série visível, opção do ECharts) e o que não muda (as
     séries completas do gráfico, os elementos do DOM). A instância do ECharts só é
     criada quando a aba abre pela primeira vez — medir a largura de um elemento
     `hidden` dá zero, então inicializar antes disso desenharia um gráfico do tamanho
     errado. */
  var registrosPorAba = {};
  var estadoAbas = {};
  var navBotoesPorAba = {};
  var paineisPorAba = {};
  var filtroBotoesPorAba = {};
  var vaziosPorAba = {};
  var instanciasAtivas = [];
  var abaAtivaId = null;

  function montaGrafico(grafico, dados, abaId) {
    var seriesTodas = grafico.series.map(function (id) {
      var serie = Object.assign({ serie_id: id }, dados.series[id]);
      // `rotulos` no gráfico sobrescreve o rótulo do catálogo — necessário quando o
      // mesmo rótulo se repetiria na legenda (três séries do Brasil, por exemplo).
      if (grafico.rotulos && grafico.rotulos[id]) serie.rotulo = grafico.rotulos[id];
      return serie;
    });

    // `inicio` do próprio gráfico sobrescreve o recorte geral de abas.yaml.
    var corte = grafico.inicio || (dados.recorte && dados.recorte.inicio) || null;
    seriesTodas.forEach(function (s) { s.visivel = recorta(s, corte); });

    // Recorte posterior ao fim de TODAS as séries do gráfico: melhor mostrar a série
    // inteira do que um gráfico vazio. É uma decisão sobre o recorte de tempo, então
    // vale para as séries todas, antes do filtro de segmento entrar em cena.
    if (seriesTodas.every(function (s) { return !s.visivel.length; })) {
      seriesTodas.forEach(function (s) { s.visivel = s.obs; });
    }

    var cartao = elemento('section', 'grafico');
    cartao.appendChild(elemento('h2', null, grafico.titulo));

    var subtituloEl = elemento('p', 'grafico__subtitulo');
    cartao.appendChild(subtituloEl);

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

    // Linhas de procedência por série e o aviso de recorte: mudam a cada troca de
    // filtro, por isso ficam num contêiner à parte, que só ele é limpo e reconstruído.
    var dinamico = elemento('div', 'grafico__meta-dinamica');
    meta.appendChild(dinamico);

    var acoes = elemento('div', 'grafico__acoes');

    /* Caminho relativo a docs/, não a data/: o GitHub Pages publica apenas docs/, e
       build_xlsx.py deixa uma cópia da planilha aqui exatamente por isso. Assim o mesmo
       href funciona por file:// e no site. */
    var planilha = elemento('a', 'baixar', 'Baixar todas as séries (XLSX)');
    planilha.href = ARQUIVO_XLSX;
    planilha.setAttribute('download', '');
    acoes.appendChild(planilha);

    var registro = {
      abaId: abaId,
      def: grafico,
      seriesTodas: seriesTodas,
      corte: corte,
      cartao: cartao,
      subtituloEl: subtituloEl,
      dinamicoEl: dinamico,
      area: area,
      instancia: null,
      opcaoAtual: null,
      seriesVisiveis: [],
      corteAtual: null
    };

    var botao = elemento('button', 'baixar', 'Baixar este gráfico (CSV)');
    botao.type = 'button';
    botao.addEventListener('click', function () {
      baixar(nomeArquivo(grafico.titulo), csv(grafico, registro.seriesVisiveis, registro.corteAtual));
    });
    acoes.appendChild(botao);

    meta.appendChild(acoes);
    cartao.appendChild(meta);

    return { cartao: cartao, registro: registro };
  }

  /* Recalcula o que o filtro de segmento decide: quais séries entram, o período do
     subtítulo, as linhas de procedência e a opção do ECharts. Não desenha nada sozinha
     — se o gráfico já tem instância, aplica a opção nova; se ainda não tem (aba nunca
     aberta), só deixa `opcaoAtual` pronta para quando `garanteInicializado` rodar. */
  function atualizaGrafico(registro) {
    var segmento = (estadoAbas[registro.abaId] || {}).segmento || SEGMENTO_PADRAO;
    var series = registro.seriesTodas.filter(function (s) { return serieNoFiltro(s, segmento); });

    if (!series.length) {
      // Nenhuma série do gráfico serve este segmento — por exemplo, um gráfico só de
      // pessoas jurídicas sob o filtro Família. O cartão inteiro some da grade.
      registro.cartao.hidden = true;
      registro.seriesVisiveis = [];
      return;
    }
    registro.cartao.hidden = false;
    registro.seriesVisiveis = series;

    var cortou = series.some(function (s) { return s.visivel.length < s.obs.length; });
    registro.corteAtual = cortou ? registro.corte : null;

    var pontos = series.reduce(function (todos, s) { return todos.concat(s.visivel); }, []);
    var inicio = pontos.reduce(function (menor, o) { return o[0] < menor ? o[0] : menor; }, pontos[0][0]);
    var fim = pontos.reduce(function (maior, o) { return o[0] > maior ? o[0] : maior; }, pontos[0][0]);

    registro.subtituloEl.textContent =
      registro.def.unidade + ' — ' +
      rotuloData(inicio, series[0].periodicidade) + ' a ' +
      rotuloData(fim, series[0].periodicidade);

    registro.dinamicoEl.innerHTML = '';
    if (cortou) {
      registro.dinamicoEl.appendChild(elemento(
        'div', null,
        'Gráfico recortado a partir de ' + registro.corte.slice(0, 4) +
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
      registro.dinamicoEl.appendChild(elemento(
        'div', null,
        origem + s.n_obs + ' observações desde ' +
        rotuloData(s.inicio, s.periodicidade) + ', última em ' +
        rotuloData(s.ultima_data, s.periodicidade) + '.'
      ));
      if (s.nota) registro.dinamicoEl.appendChild(elemento('div', 'nota', s.nota));
      if (s.status === 'stale') {
        registro.dinamicoEl.appendChild(elemento(
          'div', 'aviso-desatualizado',
          'Série desatualizada: a fonte não respondeu na última coleta e o valor exibido ' +
          'vem do cache anterior.'
        ));
      }
    });

    registro.opcaoAtual = opcoes(registro.def, series);
    if (registro.instancia) {
      registro.instancia.setOption(registro.opcaoAtual, true);
    }
  }

  /* Cria a instância do ECharts na primeira vez que o gráfico fica visível. Chamado ao
     abrir uma aba e, defensivamente, ao trocar o filtro — na prática só a primeira
     acontece, porque sob "Ambos" (o filtro inicial de toda aba) nenhum gráfico começa
     oculto. */
  function garanteInicializado(registro) {
    if (registro.instancia || registro.cartao.hidden) return;

    if (typeof echarts === 'undefined') {
      // O ECharts vem de CDN. Sem rede, o resto da página (números, fontes, downloads)
      // continua utilizável — só os gráficos não desenham.
      registro.area.className = 'carregando';
      registro.area.textContent =
        'Gráfico indisponível: a biblioteca ECharts não carregou (sem conexão). ' +
        'Os dados continuam disponíveis no botão de download.';
      return;
    }

    registro.instancia = echarts.init(registro.area, null, { renderer: 'svg' });
    registro.instancia.setOption(registro.opcaoAtual);
    instanciasAtivas.push(registro.instancia);
  }

  /* Gráfico sozinho na última linha ocupa as duas colunas, para não deixar meia linha
     vazia. Como o filtro de segmento pode ocultar cartões no meio da grade, quem decide
     isso não pode ser um seletor CSS por posição — `:nth-child`/`:last-child` contam os
     irmãos ocultos também. Por isso é recalculado aqui, sobre os cartões visíveis. */
  function ajustaUltimaLinha(abaId) {
    var visiveis = (registrosPorAba[abaId] || []).filter(function (r) { return !r.cartao.hidden; });
    visiveis.forEach(function (r) { r.cartao.classList.remove('grafico--linha-inteira'); });
    if (visiveis.length % 2 === 1) {
      visiveis[visiveis.length - 1].cartao.classList.add('grafico--linha-inteira');
    }
  }

  function atualizaEstadoVazio(abaId) {
    var registros = registrosPorAba[abaId] || [];
    var semNenhum = registros.length > 0 && registros.every(function (r) { return r.cartao.hidden; });
    if (vaziosPorAba[abaId]) vaziosPorAba[abaId].hidden = !semNenhum;
  }

  function aplicaSegmento(abaId, segmento) {
    estadoAbas[abaId].segmento = segmento;

    (filtroBotoesPorAba[abaId] || []).forEach(function (botao) {
      var ativo = botao.dataset.segmento === segmento;
      botao.classList.toggle('filtro-segmento__botao--ativo', ativo);
      botao.setAttribute('aria-pressed', ativo ? 'true' : 'false');
    });

    (registrosPorAba[abaId] || []).forEach(function (registro) {
      atualizaGrafico(registro);
      if (abaAtivaId === abaId) {
        garanteInicializado(registro);
        if (registro.instancia) registro.instancia.resize();
      }
    });

    ajustaUltimaLinha(abaId);
    atualizaEstadoVazio(abaId);
  }

  function ativarAba(id) {
    Object.keys(paineisPorAba).forEach(function (outroId) {
      var ativa = outroId === id;
      paineisPorAba[outroId].hidden = !ativa;
      navBotoesPorAba[outroId].classList.toggle('abas-nav__botao--ativo', ativa);
      navBotoesPorAba[outroId].setAttribute('aria-selected', ativa ? 'true' : 'false');
    });
    abaAtivaId = id;

    (registrosPorAba[id] || []).forEach(function (registro) {
      garanteInicializado(registro);
      // Redimensiona mesmo quando já existia: se a janela mudou de tamanho enquanto a
      // aba estava oculta, o ECharts precisa medir o container de novo agora que ele
      // voltou a ter largura real.
      if (registro.instancia) registro.instancia.resize();
    });
  }

  function montaFiltroSegmento(abaId) {
    var container = elemento('div', 'filtro-segmento');
    container.setAttribute('role', 'group');
    container.setAttribute('aria-label', 'Filtrar por família ou empresas');

    filtroBotoesPorAba[abaId] = SEGMENTOS.map(function (seg) {
      var botao = elemento('button', 'filtro-segmento__botao', seg.rotulo);
      botao.type = 'button';
      botao.dataset.segmento = seg.id;
      var ativo = seg.id === SEGMENTO_PADRAO;
      botao.classList.toggle('filtro-segmento__botao--ativo', ativo);
      botao.setAttribute('aria-pressed', ativo ? 'true' : 'false');
      botao.addEventListener('click', function () { aplicaSegmento(abaId, seg.id); });
      container.appendChild(botao);
      return botao;
    });

    return container;
  }

  function montaAba(aba, dados) {
    var painel = elemento('div', 'aba-painel');
    painel.id = 'aba-' + aba.id;
    painel.hidden = true;
    painel.setAttribute('role', 'tabpanel');

    painel.appendChild(elemento('h1', null, aba.titulo));
    if (aba.subtitulo) painel.appendChild(elemento('p', 'aba__subtitulo', aba.subtitulo));
    if (aba.nota_metodologica) {
      painel.appendChild(elemento('p', 'nota nota--aba', aba.nota_metodologica));
    }

    painel.appendChild(montaFiltroSegmento(aba.id));

    var vazio = elemento(
      'p', 'aba__vazio',
      'Nenhum gráfico desta aba está disponível para o filtro selecionado.'
    );
    vazio.hidden = true;
    painel.appendChild(vazio);
    vaziosPorAba[aba.id] = vazio;

    var grade = elemento('div', 'aba__graficos');
    registrosPorAba[aba.id] = [];
    aba.graficos.forEach(function (grafico) {
      var montado = montaGrafico(grafico, dados, aba.id);
      grade.appendChild(montado.cartao);
      registrosPorAba[aba.id].push(montado.registro);
      atualizaGrafico(montado.registro);
    });
    painel.appendChild(grade);

    ajustaUltimaLinha(aba.id);
    atualizaEstadoVazio(aba.id);

    return painel;
  }

  // ------------------------------------------------------------------ montagem

  function monta() {
    var dados = window.MONITOR;
    var nav = document.getElementById('abas-nav');
    var paineis = document.getElementById('abas-paineis');

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

    nav.innerHTML = '';
    paineis.innerHTML = '';
    registrosPorAba = {};
    estadoAbas = {};
    navBotoesPorAba = {};
    paineisPorAba = {};
    filtroBotoesPorAba = {};
    vaziosPorAba = {};
    instanciasAtivas = [];
    abaAtivaId = null;

    dados.abas.forEach(function (aba) {
      estadoAbas[aba.id] = { segmento: SEGMENTO_PADRAO };

      var botaoNav = elemento('button', 'abas-nav__botao', aba.titulo);
      botaoNav.type = 'button';
      botaoNav.setAttribute('role', 'tab');
      botaoNav.addEventListener('click', function () { ativarAba(aba.id); });
      nav.appendChild(botaoNav);
      navBotoesPorAba[aba.id] = botaoNav;

      var painel = montaAba(aba, dados);
      paineis.appendChild(painel);
      paineisPorAba[aba.id] = painel;
    });

    montaMetodologia(dados);

    window.addEventListener('resize', function () {
      instanciasAtivas.forEach(function (i) { i.resize(); });
    });

    if (dados.abas.length) ativarAba(dados.abas[0].id);
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
