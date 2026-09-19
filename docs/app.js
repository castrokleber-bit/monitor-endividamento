/* Monitor de Endividamento — montagem da página.
 *
 * Sem build step: lê `window.MONITOR`, gerado por src/build_dataset.py e carregado por
 * dados.js. O payload vem embutido num <script> justamente para que a página funcione
 * tanto por file:// quanto servida no GitHub Pages, com o mesmo código.
 *
 * Este arquivo NÃO interpreta dado. Não deflaciona, não divide pelo PIB, não calcula
 * variação, não completa lacuna, não arredonda valor armazenado. As quatro bases do
 * seletor chegam prontas do pipeline, cada uma como um vetor alinhado ao eixo de datas
 * da série; aqui só se escolhe qual vetor desenhar, recorta o intervalo e formata.
 *
 * Cor sai exclusivamente das custom properties de style.css. Nenhum hex aqui.
 */
(function () {
  'use strict';

  var MESES_TRI = { 1: '1º tri', 4: '2º tri', 7: '3º tri', 10: '4º tri' };
  var MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

  // Cópia que build_xlsx.py deixa em docs/. O original versionado fica em data/.
  var ARQUIVO_XLSX = 'monitor_endividamento.xlsx';

  var ID_ABA_METODOLOGIA = 'metodologia';

  var raiz = getComputedStyle(document.documentElement);
  function token(nome) {
    return raiz.getPropertyValue(nome).trim();
  }

  var PALETA = ['--serie-1', '--serie-2', '--serie-3', '--serie-4', '--serie-5'].map(token);
  var COR_TEXTO = token('--cinza');
  var COR_GRID = token('--cinza-claro');
  var COR_FUNDO = token('--fundo');

  /* Mais séries que cores. G8 tem oito curvas, a abertura da indústria em G16 tem vinte,
     e a identidade visual fixa a paleta em cinco tokens — estendê-la seria inventar cor
     institucional, o que depende de decisão humana. A saída é variar o TRAÇO depois de
     esgotar as cores: sólido, tracejado, pontilhado. Distingue as curvas sem sair da
     paleta e, de quebra, continua legível em preto e branco, que é justamente a
     preocupação registrada na decisão de 30/08/2026 sobre a paleta. */
  var TRACOS = ['solid', 'dashed', 'dotted'];

  var semAnimacao = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ------------------------------------------------------------------ formatação

  function casasDecimais(unidade) {
    // Regra fixa de exibição — não altera o valor armazenado.
    if (!unidade) return 2;
    if (unidade.indexOf('R$') >= 0) return 1;
    return 2;
  }

  function numero(valor, unidade) {
    var casas = casasDecimais(unidade);
    return valor.toLocaleString('pt-BR', {
      minimumFractionDigits: casas,
      maximumFractionDigits: casas
    });
  }

  /* No eixo a precisão cheia vira ruído: 50,00 não diz mais que 50. O tooltip e o CSV
     seguem com o valor como o pipeline o calculou. */
  function numeroEixo(valor) {
    return valor.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 1 });
  }

  function partesData(iso) {
    var p = iso.split('-');
    return { ano: p[0], mes: parseInt(p[1], 10) };
  }

  function rotuloData(iso, periodicidade) {
    var d = partesData(iso);
    if (periodicidade === 'A') return d.ano;
    if (periodicidade === 'T') return (MESES_TRI[d.mes] || d.mes) + '/' + d.ano;
    return MESES[d.mes - 1] + '/' + d.ano;
  }

  function elemento(tag, classe, texto) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (texto != null) el.textContent = texto;
    return el;
  }

  function anosAntes(iso, anos) {
    var p = iso.split('-');
    return (parseInt(p[0], 10) - anos) + '-' + p[1] + '-' + p[2];
  }

  // ------------------------------------------------------------------ markdown

  /* Markdown mínimo para o texto humano de content/metodologia.md: títulos com âncora
     explícita, parágrafos, listas, **forte**, *ênfase* e `código`. Nada além disso — o
     conteúdo é escrito por pessoas, não gerado, e o front transporta em vez de
     interpretar.

     O HTML é escapado ANTES de aplicar ênfase, então nada que venha do arquivo vira
     marcação. */
  function escapaHtml(texto) {
    return texto.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function enfase(texto) {
    return texto
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>');
  }

  /* `## Título {#ancora}` vira um <h_> com id. O id é o que o ícone "i" de cada gráfico
     usa como alvo: em abas.yaml, o campo `metodologia` de um gráfico é exatamente uma
     dessas âncoras. Âncora escrita à mão de propósito — id derivado do texto mudaria
     silenciosamente se alguém reescrevesse o título, e os ícones "i" passariam a apontar
     para lugar nenhum. */
  function tituloComAncora(bruto) {
    var m = /^(#{1,4})\s+([\s\S]+)$/.exec(bruto);
    if (!m) return null;
    var texto = m[2].trim();
    var ancora = null;
    var comId = /^([\s\S]+?)\s*\{#([a-z0-9-]+)\}$/.exec(texto);
    if (comId) {
      texto = comId[1].trim();
      ancora = comId[2];
    }
    return { nivel: m[1].length, texto: texto, ancora: ancora };
  }

  function markdown(destino, texto, nivelBase, blocos) {
    var base = nivelBase || 1;
    var primeiro = true;
    texto.split(/\n\s*\n/).forEach(function (bruto) {
      var trecho = bruto.trim();
      if (!trecho) return;

      /* O `#` de abertura do arquivo é o título do documento, e o painel já desenha um
         <h1> com ele. Renderizar os dois deixaria o título duplicado na tela. */
      if (primeiro) {
        primeiro = false;
        if (/^#\s/.test(trecho)) return;
      }

      // Marcador de bloco gerado: o parágrafo inteiro é `{{fontes}}`, `{{ficha}}` etc.
      var marcador = /^\{\{([a-z_]+)\}\}$/.exec(trecho);
      if (marcador) {
        var bloco = (blocos || []).filter(function (b) { return b.tipo === marcador[1]; })[0];
        if (bloco) destino.appendChild(montaBlocoGerado(bloco));
        return;
      }

      var titulo = tituloComAncora(trecho);
      if (titulo) {
        var h = elemento('h' + Math.min(base + titulo.nivel - 1, 6), null, titulo.texto);
        if (titulo.ancora) h.id = titulo.ancora;
        destino.appendChild(h);
        return;
      }

      if (/^[-*]\s+/.test(trecho)) {
        /* Um item de lista pode ocupar várias linhas no arquivo: o texto é escrito em
           colunas de 90 caracteres e as continuações vêm indentadas. Linha que não
           começa com marcador pertence ao item anterior — descartá-la, como a versão
           anterior fazia, cortava a frase no meio. */
        var itens = [];
        trecho.split(/\n/).forEach(function (linha) {
          var marcado = /^[-*]\s+([\s\S]+)$/.exec(linha.trim());
          if (marcado) {
            itens.push(marcado[1]);
          } else if (itens.length) {
            itens[itens.length - 1] += ' ' + linha.trim();
          }
        });
        var ul = elemento('ul', 'metodologia__lista');
        itens.forEach(function (texto_item) {
          var li = document.createElement('li');
          li.innerHTML = enfase(escapaHtml(texto_item));
          ul.appendChild(li);
        });
        destino.appendChild(ul);
        return;
      }

      var p = elemento('p', 'metodologia__p');
      p.innerHTML = enfase(escapaHtml(trecho.replace(/\s*\n\s*/g, ' ')));
      destino.appendChild(p);
    });
  }

  // ------------------------------------------------------------------ séries

  function serieDoPayload(id, grafico) {
    var dados = window.MONITOR;
    var serie = Object.assign({ serie_id: id }, dados.series[id]);
    // `rotulos` no gráfico sobrescreve o rótulo do catálogo — necessário quando o mesmo
    // rótulo se repetiria na legenda (três séries do Brasil, por exemplo).
    if (grafico.rotulos && grafico.rotulos[id]) serie.rotulo = grafico.rotulos[id];
    return serie;
  }

  /* As séries de um gráfico, já considerando o detalhamento.
   *
   * Ligar o detalhe TROCA o gráfico: em vez de acrescentar as dezesseis aberturas da
   * indústria ao lado das demais atividades, ele passa a mostrar só a indústria e as
   * suas aberturas. Acrescentar não funcionava — com o total de R$ 2,7 trilhões e
   * serviços de R$ 1,7 trilhão no mesmo eixo, as aberturas de R$ 11 a R$ 259 bilhões
   * viravam uma faixa colada no zero. Detalhar é entrar na indústria, não empilhar dois
   * níveis de agregação na mesma escala.
   *
   * A série detalhada vem primeiro e recebe o traço grosso do agregado, como o Total
   * recebe no modo normal. */
  function seriesDoGrafico(grafico, detalheAtivo) {
    var ids;
    if (detalheAtivo && grafico.detalhe) {
      ids = [grafico.detalhe.substitui].concat(grafico.detalhe.por);
    } else {
      ids = grafico.series.slice();
    }
    return ids.map(function (id, i) {
      var serie = serieDoPayload(id, grafico);
      if (detalheAtivo && grafico.detalhe && i === 0) serie.papel = 'total';
      return serie;
    });
  }

  /* Pares [data, valor] de uma série numa base, já sem as lacunas.

     O pipeline entrega um vetor por base, alinhado ao eixo de datas da série, com null
     onde a transformação não pôde ser feita — mês sem IPCA, mês sem PIB, mês sem o par
     de doze meses antes. Aqui o null é descartado: o ECharts não liga pontos ausentes e
     o CSV deixa a célula vazia. Nada é preenchido em lugar nenhum. */
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

  function unidadeDo(series, base) {
    for (var i = 0; i < series.length; i++) {
      var u = series[i].unidades[base];
      if (u) return u;
    }
    return '';
  }

  // ------------------------------------------------------------------ intervalo

  /* O intervalo visível de um gráfico. `periodo` é um dos atalhos de abas.yaml; quando
     o leitor digita um intervalo personalizado, ele vence os atalhos.

     Os anos são contados para trás a partir da ÚLTIMA observação do gráfico, não da data
     de hoje: as séries do BIS saem com um ou dois trimestres de defasagem, e "5 anos"
     contado do calendário deixaria a última faixa mais curta que as demais sem motivo. */
  function intervalo(registro, series) {
    if (registro.custom && (registro.custom.de || registro.custom.ate)) {
      return { de: registro.custom.de || null, ate: registro.custom.ate || null };
    }

    var fim = null;
    series.forEach(function (s) {
      var p = pontos(s, registro.base);
      if (p.length && (!fim || p[p.length - 1][0] > fim)) fim = p[p.length - 1][0];
    });

    var periodo = (window.MONITOR.periodos || []).filter(function (p) {
      return p.id === registro.periodo;
    })[0];

    if (!periodo || periodo.anos == null) {
      // "Tudo" — começa onde o gráfico declara, que o pipeline já calculou pela regra
      // `inicio` de abas.yaml (por padrão, a primeira data comum a todas as séries).
      return { de: registro.def.inicio || null, ate: null };
    }
    return { de: fim ? anosAntes(fim, periodo.anos) : null, ate: null };
  }

  // ------------------------------------------------------------------ gráfico

  function opcoesEcharts(registro, series, unidade) {
    var periodicidade = series[0].periodicidade;
    var base = registro.base;

    /* Referência nominal para o tooltip da variação em 12 meses: a orientação pede que
       ele mostre também o valor de onde a variação saiu. Lido do mesmo payload, nunca
       recalculado. */
    var nominais = {};
    if (base === 'var12m') {
      series.forEach(function (s) {
        var mapa = {};
        pontos(s, 'nominal').forEach(function (p) { mapa[p[0]] = p[1]; });
        nominais[s.rotulo] = { mapa: mapa, unidade: s.unidades.nominal };
      });
    }

    return {
      // As datas são o primeiro dia do período em UTC. Sem isto o ECharts converteria
      // para o fuso local e 01/06 apareceria como 31/05 no eixo.
      useUTC: true,
      animation: !semAnimacao,
      backgroundColor: COR_FUNDO,
      /* `containLabel` dimensiona a margem pelo rótulo real do eixo. Margem fixa cortava
         valores longos.

         A folga inferior acompanha a legenda. Até seis séries a legenda quebra em no
         máximo duas linhas e a folga é calculada por faixas. Acima disso ela vira
         `scroll`: uma linha só, com setas, e folga fixa. Sem isso, a abertura da
         indústria — dezessete curvas — produzia cinco linhas de legenda que invadiam o
         eixo do tempo, e nenhuma folga fixa dava conta, porque o número de linhas depende
         do comprimento dos rótulos e da largura da coluna. */
      grid: {
        left: 4,
        right: 16,
        top: 16,
        bottom: series.length > 6 ? 38 : (series.length > 3 ? 62 : (series.length > 1 ? 34 : 8)),
        containLabel: true
      },
      legend: series.length > 1
        ? {
            type: series.length > 6 ? 'scroll' : 'plain',
            bottom: 0,
            icon: 'roundRect',
            itemWidth: 14,
            itemHeight: 8,
            pageIconColor: COR_TEXTO,
            pageIconInactiveColor: COR_GRID,
            pageTextStyle: { color: COR_TEXTO, fontFamily: 'Arial, Helvetica, sans-serif' },
            textStyle: { color: COR_TEXTO, fontFamily: 'Arial, Helvetica, sans-serif', fontSize: 11 }
          }
        : undefined,
      tooltip: {
        trigger: 'axis',
        confine: true,
        backgroundColor: COR_FUNDO,
        borderColor: COR_GRID,
        textStyle: { color: COR_TEXTO, fontFamily: 'Arial, Helvetica, sans-serif' },
        formatter: function (ps) {
          var iso = new Date(ps[0].value[0]).toISOString().slice(0, 10);
          var linhas = [rotuloData(iso, periodicidade)];
          ps.forEach(function (ponto) {
            var linha = ponto.marker + ponto.seriesName + ': ' +
              numero(ponto.value[1], unidade) + ' ' + unidade;
            var ref = nominais[ponto.seriesName];
            if (ref && ref.mapa[iso] !== undefined) {
              linha += ' <span class="tooltip__ref">(de ' +
                numero(ref.mapa[iso], ref.unidade) + ' ' + ref.unidade + ')</span>';
            }
            linhas.push(linha);
          });
          return linhas.join('<br>');
        }
      },
      xAxis: {
        type: 'time',
        // Sem nome de eixo: as datas se explicam.
        axisLine: { lineStyle: { color: COR_GRID } },
        axisTick: { lineStyle: { color: COR_GRID } },
        axisLabel: { color: COR_TEXTO, fontFamily: 'Arial, Helvetica, sans-serif' }
      },
      yAxis: {
        type: 'value',
        // `scale: true` reajusta o eixo ao subconjunto visível, como a orientação pede
        // ao mudar o intervalo.
        scale: true,
        axisLine: { show: false },
        splitLine: { lineStyle: { color: COR_GRID, type: 'solid' } },
        axisLabel: {
          color: COR_TEXTO,
          fontFamily: 'Arial, Helvetica, sans-serif',
          formatter: numeroEixo
        }
      },
      series: series.map(function (s, i) {
        /* Cor e traço por POSIÇÃO no gráfico, não por identidade da série. É o que
           mantém a consistência que a orientação pede: como abas.yaml sempre põe o Total
           primeiro e as aberturas recorrentes na mesma ordem (PJ antes de PF,
           direcionado antes de livre), a mesma componente cai no mesmo slot de cor em
           todos os gráficos em que aparece. */
        var total = s.papel === 'total';
        return {
          name: s.rotulo,
          type: 'line',
          showSymbol: false,
          symbol: 'circle',
          color: PALETA[i % PALETA.length],
          lineStyle: {
            width: total ? 2.6 : 1.6,
            type: TRACOS[Math.floor(i / PALETA.length) % TRACOS.length]
          },
          emphasis: { focus: 'series' },
          data: s.visivel
        };
      })
    };
  }

  // ------------------------------------------------------------------ download

  function csv(registro, series, unidade, faixa) {
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

    var base = (window.MONITOR.bases || []).filter(function (b) {
      return b.id === registro.base;
    })[0];
    var sufixo = base ? base.sufixo : '';

    var linhas = [['data'].concat(series.map(function (s) {
      return s.serie_id + sufixo;
    })).join(';')];

    ordenadas.forEach(function (data) {
      linhas.push([data].concat(indices.map(function (mapa) {
        // Ponto decimal e campo vazio para lacuna — nada é preenchido.
        return mapa[data] === undefined ? '' : String(mapa[data]);
      })).join(';'));
    });

    var cabecalho = [
      '# ' + registro.def.titulo,
      '# base: ' + (base ? base.rotulo : 'valores da fonte'),
      '# unidade: ' + unidade,
      '# fonte: ' + fonteDoGrafico(series),
      '# intervalo exibido: ' + (faixa.de || 'início da série') + ' a ' + (faixa.ate || 'último dado'),
      '# a planilha XLSX traz cada série inteira, desde a primeira observação da fonte',
      '# gerado do Monitor de Endividamento em ' + window.MONITOR.gerado_em
    ].join('\n');

    return cabecalho + '\n' + linhas.join('\n') + '\n';
  }

  function baixarTexto(nome, conteudo, mime) {
    // BOM para o Excel abrir o CSV em UTF-8 sem estragar os acentos.
    var blob = new Blob(['﻿' + conteudo], { type: mime });
    baixarBlobUrl(nome, URL.createObjectURL(blob), true);
  }

  function baixarBlobUrl(nome, url, revogar) {
    var a = document.createElement('a');
    a.href = url;
    a.download = nome;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    if (revogar) setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function nomeArquivo(titulo, extensao) {
    return titulo
      .toLowerCase()
      .normalize('NFD')
      // remove as marcas combinantes soltas pelo NFD (U+0300–U+036F)
      .replace(new RegExp('[\\u0300-\\u036f]', 'g'), '')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '') + '.' + extensao;
  }

  function fonteDoGrafico(series) {
    var fontes = [];
    series.forEach(function (s) {
      if (fontes.indexOf(s.fonte) < 0) fontes.push(s.fonte);
    });
    return fontes.join(' e ');
  }

  // ------------------------------------------------------------------ estado

  /* Um registro por gráfico, vivo enquanto a página existe. A instância do ECharts só é
     criada quando a aba abre pela primeira vez — medir a largura de um elemento `hidden`
     dá zero, então inicializar antes disso desenharia um gráfico do tamanho errado. */
  var registrosPorAba = {};
  var navBotoesPorAba = {};
  var paineisPorAba = {};
  var instanciasAtivas = [];
  var abaAtivaId = null;

  // ------------------------------------------------------------------ controles

  function montaSeletorBase(registro) {
    var bases = (window.MONITOR.bases || []).filter(function (b) {
      return registro.def.bases.indexOf(b.id) >= 0;
    });
    // Um gráfico com uma base só não ganha seletor: um menu de uma opção é ruído.
    if (bases.length < 2) return null;

    var envolucro = elemento('label', 'controle');
    envolucro.appendChild(elemento('span', 'controle__rotulo', 'Base'));
    var select = elemento('select', 'controle__campo');
    bases.forEach(function (b) {
      var opcao = elemento('option', null, b.rotulo);
      opcao.value = b.id;
      if (b.id === registro.base) opcao.selected = true;
      select.appendChild(opcao);
    });
    select.addEventListener('change', function () {
      registro.base = select.value;
      desenha(registro);
    });
    envolucro.appendChild(select);
    return envolucro;
  }

  function montaSeletorPeriodo(registro, aoMudar) {
    var envolucro = elemento('label', 'controle');
    envolucro.appendChild(elemento('span', 'controle__rotulo', 'Período'));
    var select = elemento('select', 'controle__campo');
    (window.MONITOR.periodos || []).forEach(function (p) {
      var opcao = elemento('option', null, p.rotulo);
      opcao.value = p.id;
      select.appendChild(opcao);
    });
    var personalizado = elemento('option', null, 'Personalizado…');
    personalizado.value = '__custom';
    select.appendChild(personalizado);
    select.value = registro ? registro.periodo : window.MONITOR.periodo_padrao;
    select.addEventListener('change', aoMudar);
    envolucro.appendChild(select);
    return { envolucro: envolucro, select: select };
  }

  /* Intervalo personalizado em dois campos mês/ano. `<input type="month">` porque é o
     controle nativo para isso: o navegador já valida e já oferece o seletor certo, e
     onde ele não existe o campo degrada para texto no formato AAAA-MM, que a mesma
     leitura entende. */
  function montaCamposCustom(aoAplicar) {
    var caixa = elemento('div', 'custom');
    caixa.hidden = true;

    var de = elemento('input', 'custom__campo');
    de.type = 'month';
    de.setAttribute('aria-label', 'Mês inicial');
    var ate = elemento('input', 'custom__campo');
    ate.type = 'month';
    ate.setAttribute('aria-label', 'Mês final');

    caixa.appendChild(elemento('span', 'custom__rotulo', 'de'));
    caixa.appendChild(de);
    caixa.appendChild(elemento('span', 'custom__rotulo', 'até'));
    caixa.appendChild(ate);

    function aplica() {
      aoAplicar({
        de: de.value ? de.value + '-01' : null,
        // O campo dá o mês; o fim do intervalo tem de incluir esse mês inteiro, e as
        // séries são datadas no primeiro dia do período — daí o -01 também aqui.
        ate: ate.value ? ate.value + '-01' : null
      });
    }
    de.addEventListener('change', aplica);
    ate.addEventListener('change', aplica);

    return { caixa: caixa, de: de, ate: ate };
  }

  function montaIconeInfo(grafico) {
    if (!grafico.metodologia) return null;
    var botao = elemento('button', 'info', 'i');
    botao.type = 'button';
    botao.title = 'Ver a nota metodológica deste gráfico';
    botao.setAttribute('aria-label', 'Nota metodológica de ' + grafico.titulo);
    botao.addEventListener('click', function () {
      ativarAba(ID_ABA_METODOLOGIA);
      var alvo = document.getElementById(grafico.metodologia);
      if (alvo) {
        alvo.scrollIntoView({ behavior: semAnimacao ? 'auto' : 'smooth', block: 'start' });
        alvo.classList.add('destacado');
        setTimeout(function () { alvo.classList.remove('destacado'); }, 2200);
      }
    });
    return botao;
  }

  // ------------------------------------------------------------------ cartão

  function montaCartao(grafico, abaId) {
    var cartao = elemento('section', 'grafico');

    var topo = elemento('div', 'grafico__topo');
    var titulo = elemento('h2', 'grafico__titulo', grafico.titulo);
    topo.appendChild(titulo);

    var controles = elemento('div', 'grafico__controles');
    topo.appendChild(controles);
    cartao.appendChild(topo);

    var subtitulo = elemento('p', 'grafico__subtitulo');
    cartao.appendChild(subtitulo);

    var area = elemento('div', 'grafico__area');
    cartao.appendChild(area);

    var rodape = elemento('div', 'grafico__rodape');
    var meta = elemento('div', 'grafico__meta');
    rodape.appendChild(meta);
    var acoes = elemento('div', 'grafico__acoes');
    rodape.appendChild(acoes);
    cartao.appendChild(rodape);

    var registro = {
      abaId: abaId,
      def: grafico,
      cartao: cartao,
      areaEl: area,
      subtituloEl: subtitulo,
      metaEl: meta,
      base: grafico.base_padrao || 'nominal',
      periodo: window.MONITOR.periodo_padrao,
      custom: null,
      detalhe: false,
      instancia: null,
      opcaoAtual: null,
      seriesVisiveis: [],
      unidadeAtual: '',
      faixaAtual: { de: null, ate: null }
    };

    var seletorBase = montaSeletorBase(registro);
    if (seletorBase) controles.appendChild(seletorBase);

    var campos = montaCamposCustom(function (valores) {
      registro.custom = valores;
      desenha(registro);
    });
    var periodo = montaSeletorPeriodo(registro, function () {
      if (periodo.select.value === '__custom') {
        campos.caixa.hidden = false;
        return;
      }
      campos.caixa.hidden = true;
      registro.custom = null;
      registro.periodo = periodo.select.value;
      desenha(registro);
    });
    registro.periodoSelect = periodo.select;
    registro.camposCustom = campos;
    controles.appendChild(periodo.envolucro);

    if (grafico.detalhe) {
      var alternar = elemento('label', 'controle controle--caixa');
      var caixa = elemento('input');
      caixa.type = 'checkbox';
      caixa.addEventListener('change', function () {
        registro.detalhe = caixa.checked;
        desenha(registro);
      });
      alternar.appendChild(caixa);
      alternar.appendChild(elemento('span', null, grafico.detalhe.rotulo));
      controles.appendChild(alternar);
    }

    var info = montaIconeInfo(grafico);
    if (info) controles.appendChild(info);

    /* Os campos do intervalo personalizado ficam DENTRO do topo, não como filho direto
       do cartão. O cartão alinha os seus quatro filhos com os do cartão vizinho por
       `subgrid`, e um quinto filho que aparece e some conforme o leitor abre o
       "Personalizado…" desalinharia as duas curvas de uma mesma linha da grade. */
    topo.appendChild(campos.caixa);

    var png = elemento('button', 'baixar', 'PNG');
    png.type = 'button';
    png.title = 'Baixar a imagem do gráfico';
    png.addEventListener('click', function () {
      if (!registro.instancia) return;
      baixarBlobUrl(
        nomeArquivo(grafico.titulo, 'png'),
        registro.instancia.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: COR_FUNDO }),
        false
      );
    });
    acoes.appendChild(png);

    var botaoCsv = elemento('button', 'baixar', 'CSV');
    botaoCsv.type = 'button';
    botaoCsv.title = 'Baixar as séries deste gráfico';
    botaoCsv.addEventListener('click', function () {
      baixarTexto(
        nomeArquivo(grafico.titulo, 'csv'),
        csv(registro, registro.seriesVisiveis, registro.unidadeAtual, registro.faixaAtual),
        'text/csv;charset=utf-8'
      );
    });
    acoes.appendChild(botaoCsv);

    return registro;
  }

  /* Recalcula tudo o que depende da base, do intervalo e do detalhamento, e redesenha.
     Se o gráfico ainda não tem instância (aba nunca aberta), só deixa a opção pronta
     para quando `garanteInicializado` rodar. */
  function desenha(registro) {
    var series = seriesDoGrafico(registro.def, registro.detalhe);
    var faixa = intervalo(registro, series);
    var unidade = unidadeDo(series, registro.base);

    series.forEach(function (s) {
      s.visivel = recorta(pontos(s, registro.base), faixa.de, faixa.ate);
    });

    /* Intervalo que não pega observação nenhuma: melhor mostrar a série inteira do que
       um gráfico vazio. Acontece quando o leitor digita um intervalo anterior ao início
       da série. */
    var vazio = series.every(function (s) { return !s.visivel.length; });
    if (vazio) {
      series.forEach(function (s) { s.visivel = pontos(s, registro.base); });
      faixa = { de: null, ate: null };
    }
    series = series.filter(function (s) { return s.visivel.length; });
    if (!series.length) return;

    registro.seriesVisiveis = series;
    registro.unidadeAtual = unidade;
    registro.faixaAtual = faixa;

    var inicio = series[0].visivel[0][0];
    var fim = series[0].visivel[series[0].visivel.length - 1][0];
    series.forEach(function (s) {
      if (s.visivel[0][0] < inicio) inicio = s.visivel[0][0];
      var ultimo = s.visivel[s.visivel.length - 1][0];
      if (ultimo > fim) fim = ultimo;
    });

    var p = series[0].periodicidade;
    registro.subtituloEl.textContent =
      unidade + ' — ' + rotuloData(inicio, p) + ' a ' + rotuloData(fim, p);

    /* O cartão não carrega texto explicativo: só a procedência e o último ponto. A
       explicação vive na aba Metodologia, alcançável pelo ícone "i".

       Um valor só, o da primeira série — que é sempre o agregado, pela ordem fixada em
       abas.yaml. Listar o último ponto de todas viraria parede de texto nos gráficos de
       oito curvas, e o tooltip já dá os demais ao passar o mouse. */
    var principal = series[0];
    var ultimo = principal.visivel[principal.visivel.length - 1];
    registro.metaEl.textContent =
      'Fonte: ' + fonteDoGrafico(series) + '. ' + principal.rotulo + ' em ' +
      rotuloData(ultimo[0], p) + ': ' + numero(ultimo[1], unidade) + ' ' + unidade + '.';

    registro.opcaoAtual = opcoesEcharts(registro, series, unidade);
    if (registro.instancia) {
      // `true` descarta a opção anterior: sem isso o ECharts mescla, e uma troca que
      // reduz o número de curvas (desligar o detalhamento) deixaria curvas órfãs.
      registro.instancia.setOption(registro.opcaoAtual, true);
    }
  }

  function garanteInicializado(registro) {
    if (registro.instancia) return;

    if (typeof echarts === 'undefined') {
      // O ECharts vem de CDN. Sem rede, o resto da página (números, procedência,
      // downloads) continua utilizável — só os gráficos não desenham.
      registro.areaEl.className = 'carregando';
      registro.areaEl.textContent =
        'Gráfico indisponível: a biblioteca ECharts não carregou (sem conexão). ' +
        'Os dados continuam disponíveis nos botões de download.';
      return;
    }

    registro.instancia = echarts.init(registro.areaEl, null, { renderer: 'svg' });
    if (registro.opcaoAtual) registro.instancia.setOption(registro.opcaoAtual);
    instanciasAtivas.push(registro.instancia);
  }

  /* Gráfico sozinho na última linha ocupa as duas colunas, para não deixar meia linha
     vazia. Fica em JavaScript, e não num `:nth-child` do CSS, porque a contagem tem de
     ser dos cartões VISÍVEIS — e um gráfico pode não ser montado quando as séries dele
     não vieram naquela coleta. */
  function ajustaUltimaLinha(abaId) {
    var visiveis = (registrosPorAba[abaId] || []).filter(function (r) { return !r.cartao.hidden; });
    visiveis.forEach(function (r) { r.cartao.classList.remove('grafico--linha-inteira'); });
    if (visiveis.length % 2 === 1) {
      visiveis[visiveis.length - 1].cartao.classList.add('grafico--linha-inteira');
    }
  }

  // ------------------------------------------------------------------ abas

  /* Controle de período da aba inteira. A orientação é explícita: quando acionado, ele
     sobrescreve os seletores individuais. Por isso ele também atualiza o `select` de
     cada cartão — deixar os dois mostrando coisas diferentes seria uma interface que
     mente sobre o que está na tela. */
  function montaControleGlobal(abaId) {
    var barra = elemento('div', 'aba__controles');
    barra.appendChild(elemento('span', 'aba__controles-rotulo', 'Aplicar a todos os gráficos desta aba:'));

    var campos = montaCamposCustom(function (valores) {
      (registrosPorAba[abaId] || []).forEach(function (r) {
        r.custom = valores;
        r.periodoSelect.value = '__custom';
        r.camposCustom.caixa.hidden = false;
        r.camposCustom.de.value = valores.de ? valores.de.slice(0, 7) : '';
        r.camposCustom.ate.value = valores.ate ? valores.ate.slice(0, 7) : '';
        desenha(r);
        if (r.instancia) r.instancia.resize();
      });
    });

    var periodo = montaSeletorPeriodo(null, function () {
      if (periodo.select.value === '__custom') {
        campos.caixa.hidden = false;
        return;
      }
      campos.caixa.hidden = true;
      (registrosPorAba[abaId] || []).forEach(function (r) {
        r.custom = null;
        r.periodo = periodo.select.value;
        r.periodoSelect.value = periodo.select.value;
        r.camposCustom.caixa.hidden = true;
        desenha(r);
        if (r.instancia) r.instancia.resize();
      });
    });

    barra.appendChild(periodo.envolucro);
    barra.appendChild(campos.caixa);
    return barra;
  }

  function montaAba(aba) {
    var painel = elemento('div', 'aba-painel');
    painel.id = 'aba-' + aba.id;
    painel.hidden = true;
    painel.setAttribute('role', 'tabpanel');

    painel.appendChild(elemento('h1', null, aba.titulo));
    if (aba.subtitulo) painel.appendChild(elemento('p', 'aba__subtitulo', aba.subtitulo));
    if (aba.nota_metodologica) {
      painel.appendChild(elemento('p', 'nota nota--aba', aba.nota_metodologica));
    }

    painel.appendChild(montaControleGlobal(aba.id));

    var grade = elemento('div', 'aba__graficos');
    registrosPorAba[aba.id] = [];
    aba.graficos.forEach(function (grafico) {
      var registro = montaCartao(grafico, aba.id);
      grade.appendChild(registro.cartao);
      registrosPorAba[aba.id].push(registro);
      desenha(registro);
    });
    painel.appendChild(grade);

    ajustaUltimaLinha(aba.id);
    return painel;
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
      // aba estava oculta, o ECharts precisa medir o container de novo agora.
      if (registro.instancia) registro.instancia.resize();
    });
  }

  // ------------------------------------------------------------------ metodologia

  /* `alta: true` confina a tabela num painel com rolagem própria e cabeçalho fixo. A
     ficha tem mais de cem linhas: solta na página, ela empurrava o histórico para treze
     mil pixels abaixo e tornava a aba inteira difícil de percorrer. */
  function tabela(colunas, linhas, classe, alta) {
    var envolucro = elemento('div', 'tabela-rolavel' + (alta ? ' tabela-rolavel--alta' : ''));
    var t = elemento('table', classe || 'tabela');
    var thead = document.createElement('thead');
    var tr = document.createElement('tr');
    colunas.forEach(function (c) { tr.appendChild(elemento('th', null, c.titulo)); });
    thead.appendChild(tr);
    t.appendChild(thead);

    var tbody = document.createElement('tbody');
    linhas.forEach(function (linha) {
      var l = document.createElement('tr');
      colunas.forEach(function (c) {
        var valor = c.valor(linha);
        l.appendChild(elemento('td', c.classe, valor == null || valor === '' ? '—' : String(valor)));
      });
      tbody.appendChild(l);
    });
    t.appendChild(tbody);
    envolucro.appendChild(t);
    return envolucro;
  }

  function dataBr(iso) {
    if (!iso) return '';
    var p = String(iso).slice(0, 10).split('-');
    return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : iso;
  }

  function montaBlocoGerado(bloco) {
    var secao = elemento('section', 'bloco');
    secao.id = 'bloco-' + bloco.tipo;
    secao.appendChild(elemento('h2', null, bloco.titulo));

    if (bloco.tipo === 'fontes') {
      secao.appendChild(elemento('p', 'metodologia__p',
        'Frequência de coleta: ' + bloco.frequencia +
        ' Última atualização: ' + bloco.atualizado_em + ' (horário de Brasília).' +
        ' Próxima coleta prevista: ' + dataBr(bloco.proxima_coleta) + '.'));
      secao.appendChild(tabela([
        { titulo: 'Fonte', valor: function (l) { return l.fonte; } },
        { titulo: 'Séries', valor: function (l) { return l.n_series; } },
        { titulo: 'Observação mais recente', valor: function (l) { return dataBr(l.ultima_obs); } }
      ], bloco.linhas));
      return secao;
    }

    if (bloco.tipo === 'transformacoes') {
      secao.appendChild(elemento('p', 'metodologia__p',
        'Mês-base do deflator nesta atualização: ' + (bloco.base_deflator || '—') +
        ' (série ' + (bloco.codigo_deflator || '—') + ').' +
        ' Vintage do PIB usado no denominador: ' + (bloco.vintage_pib || '—') +
        ' (série ' + (bloco.codigo_pib || '—') + ').' +
        ' Os dois são móveis e mudam a cada atualização, por isso esta seção é gerada ' +
        'pelo pipeline e não escrita à mão.'));
      secao.appendChild(tabela([
        { titulo: 'Base', valor: function (l) { return l.rotulo; } },
        { titulo: 'Sufixo na planilha', valor: function (l) { return l.sufixo; }, classe: 'mono' },
        { titulo: 'Regra', valor: function (l) { return l.regra; } }
      ], bloco.linhas));
      return secao;
    }

    if (bloco.tipo === 'derivadas') {
      secao.appendChild(elemento('p', 'metodologia__p',
        'Séries que não existem em fonte nenhuma: são calculadas pelo pipeline a partir ' +
        'das séries coletadas, pela fórmula abaixo. Uma data só entra no resultado ' +
        'quando todas as séries envolvidas têm observação naquela data.'));
      secao.appendChild(tabela([
        { titulo: 'Série', valor: function (l) { return l.serie_id; }, classe: 'mono' },
        { titulo: 'Operação', valor: function (l) { return l.operacao; } },
        { titulo: 'Fórmula (códigos da fonte)', valor: function (l) { return l.formula; } },
        { titulo: 'Unidade', valor: function (l) { return l.unidade; } }
      ], bloco.linhas));
      return secao;
    }

    if (bloco.tipo === 'ficha') {
      secao.appendChild(elemento('p', 'metodologia__p',
        bloco.linhas.length + ' séries. A tabela é gerada do catálogo a cada atualização; ' +
        'nenhuma linha é escrita à mão. A coluna "conversão" registra toda mudança de ' +
        'unidade entre o que a fonte publica e o que a página exibe.'));
      secao.appendChild(tabela([
        { titulo: 'Série', valor: function (l) { return l.serie_id; }, classe: 'mono' },
        { titulo: 'Nome na fonte', valor: function (l) { return l.nome_oficial; } },
        { titulo: 'Fonte', valor: function (l) { return l.fonte; } },
        { titulo: 'Código', valor: function (l) { return l.codigo; }, classe: 'mono' },
        { titulo: 'Tabela de origem', valor: function (l) { return l.tabela; } },
        { titulo: 'Unidade original', valor: function (l) { return l.unidade_origem; } },
        { titulo: 'Unidade exibida', valor: function (l) { return l.unidade_exibicao; } },
        { titulo: 'Conversão', valor: function (l) { return l.conversao; } },
        { titulo: 'Segmento', valor: function (l) { return l.segmento; } },
        { titulo: 'Primeira obs.', valor: function (l) { return dataBr(l.primeira_obs); } },
        { titulo: 'Última obs.', valor: function (l) { return dataBr(l.ultima_obs); } },
        { titulo: 'Obs.', valor: function (l) { return l.n_obs; } },
        { titulo: 'Gráficos', valor: function (l) { return (l.graficos || []).join(' · '); } }
      ], bloco.linhas, 'tabela tabela--ficha', true));
      return secao;
    }

    if (bloco.tipo === 'historico') {
      if (!bloco.linhas.length) {
        secao.appendChild(elemento('p', 'metodologia__p',
          'Ainda não há histórico registrado: este arquivo começa a ser preenchido na ' +
          'primeira atualização depois desta.'));
        return secao;
      }
      secao.appendChild(elemento('p', 'metodologia__p',
        'Gerado pelo pipeline comparando o estado de cada série com o da execução ' +
        'anterior. "Revisada" é a série cuja última observação não avançou mas cujo ' +
        'número de observações mudou — a fonte reescreveu o histórico, o que é ' +
        'comportamento normal do Banco Central.'));
      secao.appendChild(tabela([
        { titulo: 'Data', valor: function (l) { return dataBr(l.data); } },
        { titulo: 'Séries', valor: function (l) { return l.n_series; } },
        { titulo: 'Novas', valor: function (l) { return (l.novas || []).join(', '); } },
        {
          titulo: 'Avançaram',
          valor: function (l) {
            return (l.avancaram || []).map(function (a) {
              return a.serie_id + ' (' + dataBr(a.de) + ' → ' + dataBr(a.para) + ')';
            }).join('; ');
          }
        },
        {
          titulo: 'Revisadas',
          valor: function (l) {
            return (l.revisadas || []).map(function (r) {
              return r.serie_id + ' (' + r.de + ' → ' + r.para + ' obs.)';
            }).join('; ');
          }
        }
      ], bloco.linhas, null, true));
      return secao;
    }

    return secao;
  }

  function montaAbaMetodologia(dados) {
    var painel = elemento('div', 'aba-painel aba-painel--texto');
    painel.id = 'aba-' + ID_ABA_METODOLOGIA;
    painel.hidden = true;
    painel.setAttribute('role', 'tabpanel');

    painel.appendChild(elemento('h1', null, 'Metodologia e metadados'));

    if (!dados.metodologia_texto) {
      painel.appendChild(elemento('p', 'metodologia__p',
        'content/metodologia.md não foi encontrado. Rode `python src/build_dataset.py`.'));
      return painel;
    }

    var corpo = elemento('div', 'metodologia');
    markdown(corpo, dados.metodologia_texto, 1, dados.metodologia_blocos);
    painel.appendChild(corpo);

    /* Bloco gerado que o texto humano esqueceu de chamar entra no fim, em vez de
       desaparecer. Sem isto, uma edição distraída em content/metodologia.md tiraria a
       ficha de série da página sem que nada avisasse. */
    var usados = {};
    (dados.metodologia_texto.match(/\{\{([a-z_]+)\}\}/g) || []).forEach(function (m) {
      usados[m.slice(2, -2)] = true;
    });
    (dados.metodologia_blocos || []).forEach(function (bloco) {
      if (!usados[bloco.tipo]) corpo.appendChild(montaBlocoGerado(bloco));
    });

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

    document.getElementById('atualizacao').textContent =
      'Atualizado em ' + dados.atualizado_em + ' (horário de Brasília) · ' +
      Object.keys(dados.series).length + ' séries · atualização quinzenal.';

    document.getElementById('rodape-fonte').textContent =
      'Fonte: Banco Central do Brasil (SGS) e Bank for International Settlements (BIS), ' +
      'via Federal Reserve Bank of St. Louis (FRED). Última atualização: ' +
      dados.atualizado_em + '. Ver Metodologia.';

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
    navBotoesPorAba = {};
    paineisPorAba = {};
    instanciasAtivas = [];

    function registraAba(id, titulo, painel) {
      var botao = elemento('button', 'abas-nav__botao', titulo);
      botao.type = 'button';
      botao.setAttribute('role', 'tab');
      botao.addEventListener('click', function () { ativarAba(id); });
      nav.appendChild(botao);
      navBotoesPorAba[id] = botao;
      paineis.appendChild(painel);
      paineisPorAba[id] = painel;
    }

    dados.abas.forEach(function (aba) {
      registraAba(aba.id, aba.titulo, montaAba(aba));
    });
    registraAba(ID_ABA_METODOLOGIA, 'Metodologia', montaAbaMetodologia(dados));

    window.addEventListener('resize', function () {
      instanciasAtivas.forEach(function (i) { i.resize(); });
    });

    if (dados.abas.length) ativarAba(dados.abas[0].id);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', monta);
  } else {
    monta();
  }
})();
