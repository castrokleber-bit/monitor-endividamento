# Monitor de Crédito e Endividamento

Painel público com o estoque de crédito, a inadimplência, o endividamento e o
comprometimento de renda de **famílias** e **empresas não financeiras**, no Brasil e em
benchmark internacional. Dados atualizados automaticamente via API, a cada quinze dias,
e baixáveis em XLSX.

Autoria: Kleber Pacheco de Castro.

> **Atribuição institucional suspensa (decisão de 30/08/2026).** Enquanto não houver
> validação institucional, o projeto não menciona nenhuma entidade — nem na página, nem
> na planilha, nem nos nomes dos tokens de cor. Não reintroduza nomes, siglas, assinaturas
> ou marcas institucionais sem decisão humana explícita.

---

## Princípios inegociáveis

1. **A camada de dados é 100% determinística.** Nenhuma interpretação, arredondamento
   não documentado, interpolação ou preenchimento de lacuna sem regra explícita no código.
   Nada de "estimativa" gerada por IA entra em `data/`.
2. **Todo código de série vive em YAML**, nunca hardcoded em Python.
3. **Nenhum código de série entra no pipeline sem validação contra a API.**
   `src/validate_series.py` roda antes de qualquer coleta e falha o build se um código
   não responder ou se a série estiver vazia.
4. **Falha de API não publica dado parcial.** Se uma fonte cair, o pipeline reutiliza o
   cache anterior e registra `status: stale` no manifesto. A página exibe o aviso.
   No CI isso só funciona porque o workflow restaura `data/_cache/` entre execuções com
   `actions/cache` — a pasta não é versionada, e sem esse passo cada execução seria
   partida fria: série que falha vai direto para `ausente` e derruba o guard de
   regressão, em vez de virar `stale`. Não remover o passo de cache.
5. **Front sem build step.** HTML + ECharts via CDN. Tem que abrir por `file://` e
   servido em GitHub Pages, com o mesmo código.
6. **Nenhum texto interpretativo gerado por IA.** Este é um painel de dados: ele
   apresenta séries e notas metodológicas factuais, não análise. Não escreva leitura,
   diagnóstico, projeção ou recomendação. Se um texto interpretativo for desejado no
   futuro, ele é escrito por pessoas e o pipeline apenas renderiza.

## Posicionamento

A página apresenta dados públicos e notas metodológicas factuais. Não é posição
institucional de ninguém nem recomendação de investimento, e o rodapé diz isso.
Qualquer frase que possa ser lida como posicionamento sobre política monetária, crédito
ou regulação bancária precisa de validação humana antes de ir ao ar — sinalize, não
resolva.

## Arquitetura

```
config/     catálogo de séries e de séries derivadas (YAML) — fonte única da verdade
src/        ETL determinístico em Python
data/       artefatos gerados e versionados (parquet, json, xlsx, manifest)
content/    textos humanos (notas metodológicas)
docs/       GitHub Pages (index.html, app.js, style.css)
tests/      testes das transformações
```

Fluxo: `validate_series.py` → `fetch_*.py` → `build_dataset.py` (coleta, deriva,
transforma, consolida) → `build_xlsx.py` → commit.

Série calculada não é coletada: a regra vive em `config/derivadas.yaml`, a implementação
em `src/derivadas.py`, e a nota correspondente em `content/metodologia.md`. Nenhuma das
três pode faltar.

### Derivadas e transformações são coisas diferentes

Confundir as duas é o erro mais fácil de cometer neste repositório.

`src/derivadas.py` cria séries NOVAS, que não existem em fonte nenhuma: a parcela
residual que fecha a composição de um gráfico de saldo (`total − soma das parcelas`), o
total de uma tabela do BCB que não tem coluna de total publicada (`soma`), e a
inadimplência agregada por porte (`media_ponderada`). Cada uma é declarada em
`config/derivadas.yaml` e ganha entrada própria no catálogo, no parquet e na planilha.

`src/transformacoes.py` é outra coisa: são cinco maneiras de EXIBIR uma série que já
existe — R$ correntes, R$ constantes, % do PIB, variação mensal e variação em 12 meses.
Não criam série nova. Cada série declara em `bases` quais delas aceita, e
`config/abas.yaml` declara quais o seletor de um gráfico oferece. Saldo aceita as cinco;
série já em porcentagem não aceita nenhuma, porque taxa não se deflaciona nem se divide
pelo PIB.

As duas variações são calculadas sobre o valor NOMINAL, nunca sobre o deflacionado —
variação de série já deflacionada descontaria a inflação duas vezes. E nenhuma delas é
dessazonalizada: o pipeline não aplica nem remove ajuste sazonal em série nenhuma. A
variação mensal (`var1m`, decisão de 19/09/2026) é a que mais sofre com isso, e a
Metodologia avisa.

As transformações são calculadas no **pipeline**, em Python, e viajam prontas no payload
— não no navegador. Calcular no front economizaria tamanho de arquivo mas duplicaria a
fórmula, uma cópia para a planilha e outra para o gráfico, e duas implementações da mesma
regra divergem. O front não interpreta dado.

**Variação para séries em %** (diferença em pontos percentuais, mensal ou em 12 meses)
está prevista no catálogo e NÃO implementada, por decisão de 19/09/2026. Não implementar
sem nova decisão humana.

### Formato canônico

Todas as séries são normalizadas para formato longo antes de qualquer outra coisa:

| coluna | tipo | descrição |
|---|---|---|
| `serie_id` | str | slug definido no YAML (ex.: `endividamento_familias_total`) |
| `data` | date | primeiro dia do período de referência |
| `valor` | float | valor na unidade original da fonte |
| `fonte` | str | `BCB/SGS`, `FRED`, `BIS` |
| `codigo_fonte` | str | código na fonte (ex.: `29037`) |
| `unidade` | str | `%`, `% do PIB`, `R$ milhões` |
| `periodicidade` | str | `M`, `T`, `A` |

O `valor` é sempre o da FONTE, na unidade original — é isso que vai para
`data/series.parquet`, `data/series.json`, as abas temáticas da planilha e `dados_longo`.
A conversão para a unidade de exibição (R$ milhões → R$ bilhões) é declarada por série no
campo `fator` do catálogo e aplicada só na camada de exibição, em `src/transformacoes.py`.

Nunca converter unidade sem registrar a regra em `config/` e em `content/metodologia.md`.

## Armadilhas conhecidas das APIs

**BCB / SGS** (`https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json`)

- Recusa intervalos maiores que **10 anos** em séries diárias — paginar por janelas.
- Datas vêm como `dd/MM/yyyy` (string). Valores vêm como string; em algumas séries o
  separador decimal é vírgula. Sempre `.replace(".", "").replace(",", ".")` antes do cast.
- `406` = série inexistente ou parâmetro inválido. **Sob carga, o SGS responde de três
  maneiras diferentes, e todas significam a mesma coisa — "estou estrangulando você":**
  `429`, `400`, e `200` com página HTML no corpo. Nenhuma delas `comum.http_get` trata
  sozinho (ele só repete 429 e 5xx), então quem repete é quem conhece o formato esperado:
  `validate_series._observacao_mais_recente` e `fetch_bcb._pede_json`, com espera de
  2s, 4s e 8s. Backoff curto não vence throttling — em 19/09/2026, com 1,4s e 2,8s,
  sete séries ainda reprovaram com 400.
- **A assinatura de estrangulamento é o BLOCO CONTÍGUO.** Quando falham séries vizinhas
  na ordem do catálogo, e as mesmas passavam minutos antes, é a fonte e não o código.
  Código errado falha sozinho e falha sempre.
- **O ritmo importa e mudou com o tamanho do catálogo.** Com 42 séries, 0,7s entre
  chamadas bastava. Com 108, a validação virou 103 requisições em rajada contínua e
  passou a ser recusada; `validate_series.PAUSA` subiu para 1,2s. Quem acrescentar muitas
  séries de uma vez precisa reavaliar isso.
- Resposta pode vir como HTML de erro com status 200. Validar que o payload é lista de
  dicts — e REPETIR, porque esse é o sinal de que a API está sob carga, não de que o
  código está errado. `comum.http_get` não consegue fazer isso sozinho: para ele, 200 foi
  sucesso. Quem repete é quem sabe o formato esperado — `validate_series` tem retry
  próprio com backoff, e `fetch_bcb` cai para janelas de data. Em 19/09/2026, sem esse
  retry, uma instabilidade momentânea do BCB reprovou dezesseis séries consecutivas que
  haviam passado minutos antes, e derrubou o build inteiro.
- **Há série que RECUSA a consulta sem intervalo.** Descoberto em 19/09/2026 na série
  27703: a consulta aberta devolve `{"erro":{}}` com status 200, e `/dados/ultimos/N`
  responde 400 para N maior que 20; com `dataInicial`/`dataFinal` ela entrega os 175
  meses normalmente. Não há como saber de antemão quais códigos se comportam assim, então
  `fetch_bcb.py` cai para janelas de data sempre que a consulta aberta falha. Não remover
  essa queda por parecer redundante.
- **Falha de rede de UMA série não pode derrubar a execução.** `comum.http_get` levanta
  `RuntimeError` ao esgotar as tentativas de rede. A coleta já tratava isso (cai para o
  cache); a validação não, e em 19/09/2026 um read timeout na série 20541 matou o script
  inteiro com traceback no meio da lista. Um gate que morre na primeira falha de rede não
  consegue dizer quais códigos estão quebrados, que é a única coisa que se pede dele.
- **Não existe endpoint público de metadados por código.** A consulta do `sgspub` exige
  sessão de navegador e o portal de dados abertos (CKAN) só busca por texto livre,
  devolvendo pacotes de outro assunto — o código 433 traz "Ouvidorias dos bancos" em
  primeiro lugar. Conferido de novo em 19/09/2026. O nome oficial de cada série vem da
  tabela de origem do BCB anotada no catálogo (`descricao_esperada` + `tabela`), e o que
  valida o código de fato são as identidades contábeis do `build_dataset.py`.

**FRED** — exige `FRED_API_KEY`. Nunca commitar a chave; ler de variável de ambiente,
em CI vem de GitHub Secrets. Séries do BIS são servidas pelo FRED e são **trimestrais**,
com defasagem de um a dois trimestres.

**BIS** — alternativa direta via SDMX (`https://stats.bis.org/api/v1`). Usar só se o FRED
não cobrir a série desejada.

## Identidade visual (obrigatória)

**Direção visual de 19/09/2026.** Esta seção SUBSTITUI integralmente a identidade
anterior — azul `#164194`, ciano `#008BD2`, Arial e a paleta de cinco séries derivada dos
dois azuis, incluindo a decisão de 30/08/2026 sobre as posições 3 e 4. Aquela regra não
vale mais; a decisão de trocá-la é humana, registrada na orientação de direção visual
entregue nesta data. Não reintroduzir a paleta antiga sem nova decisão humana.

**Os tokens vivem em `docs/tokens.css` e em nenhum outro lugar.** Cor, tipo, espaço,
raio e sombra. `style.css` usa as variáveis; `app.js` lê os tokens com `getComputedStyle`
e nunca escreve cor literal, nem para passar ao ECharts. Quem precisar de cor nova cria
token. Um `grep` por hex fora de `tokens.css` tem de voltar vazio — inclusive no bloco de
impressão, que redefine os tokens em vez de abrir exceção.

**O conceito:** o site é um instrumento de leitura, não um painel corporativo. A
referência é um relatório de pesquisa bem editado — pouca cor, tipografia com
personalidade, muito espaço, gráficos como protagonistas. **A ousadia vai para um lugar
só: os gráficos. Todo o resto é silencioso.**

### Cor

A cor IDENTIFICA, não decora. Cada token tem papel fixo em todos os gráficos, e o papel
é declarado no campo `cor` de cada série no catálogo — nunca derivado da posição da série
no gráfico, como era antes.

| papel | token | onde |
|---|---|---|
| `total` | `--c-total` petróleo | todo agregado, e sempre com traço de 2,5px |
| `pj` | `--c-pj` ocre | pessoas jurídicas / empresas |
| `pf` | `--c-pf` ameixa | pessoas físicas / famílias |
| `livre` | `--c-livre` jade | recursos livres |
| `dir` | `--c-dir` ardósia | recursos direcionados |
| `alerta` | `--c-alerta` framboesa | endividamento e comprometimento das famílias |
| `outros` | `--c-outros` cinza-verde | residuais, com traço de 1,25px tracejado |
| `extra-1` a `extra-6` | — | modalidades e aberturas, fora da faixa semântica |

Um gráfico pode sobrescrever o papel de uma série no campo `cores`, em `config/abas.yaml`.
É necessário quando a mesma série muda de papel conforme o recorte: 20543 é a linha de PJ
nos gráficos por tomador e o agregado no gráfico de modalidades.

Gradiente existe em um lugar só: preenchimento sob a linha em gráfico de série única.

### Tipografia

**Bricolage Grotesque** nos títulos (variável, levemente condensada no título do site) e
**Hanken Grotesk** no texto e em todo número, sempre com `tabular-nums` em eixo, tooltip,
rótulo de ponta e tabela. As duas vêm do Google Fonts com `display=swap`; a página tem de
ficar legível em `system-ui` antes de elas chegarem, e sem quebrar o layout.

São a única exceção à regra de "nenhuma dependência de front além do ECharts": duas
folhas de estilo externas, sem JavaScript. Sem rede, a página inteira continua funcional.

### Gráficos

- **Rótulo na ponta da linha, sem legenda.** É o elemento memorável do site. A folga à
  direita é MEDIDA a partir do texto real, com a fonte real, e limitada a 42% da largura
  do cartão. Quando não cabe em uma linha, o rótulo quebra em duas (nome em cima, valor
  embaixo); só em último caso o nome é encurtado, e o valor nunca é cortado.
- **Hierarquia de traço:** total 2,5px, componente 1,5px, residual 1,25px tracejado.
- **Marcador só no último ponto:** cheio; vazado quando o dado é preliminar na fonte.
- **Grid horizontal apenas**, no máximo cinco linhas. Sem grid vertical, sem moldura, sem
  título de eixo. A unidade fica no topo do eixo Y.
- **Sem animação de entrada.** Só a transição de 250ms ao trocar base ou período.

### Layout

Grade de doze colunas; a largura de cada cartão vem de `largura` em `config/abas.yaml`.
Gráfico de abertura da aba 8/12, de três ou quatro séries 4/12, de modalidade 12/12. O
front estica o último cartão de uma linha incompleta para fechar as doze colunas.

O cartão carrega título, controles e gráfico — **e nada abaixo do gráfico**. Sem nota,
sem fonte, sem "última observação". A explicação toda vive na aba Metodologia, alcançada
pelo ícone "i".

Abas como pílulas, barra sticky. Aba Metodologia como página editorial, com sumário fixo
à esquerda.

### Modo escuro

`prefers-color-scheme: dark` troca o conjunto de tokens — não é inversão, é a mesma
paleta em outra chave. Como as cores dos gráficos são lidas no momento do desenho, o
front redesenha todos os gráficos quando o sistema troca de tema.

### Cache dos estáticos

`docs/index.html` referencia `app.js`, `style.css` e `tokens.css` com `?v=<hash>`, e o
carimbo é reaplicado por `build_dataset.carimba_versao()` a cada build. O hash é do
CONTEÚDO dos três arquivos, não da data: só muda quando o front muda, então a atualização
quinzenal de dados não gera diff em `index.html`.

Isso não é zelo abstrato. O GitHub Pages serve tudo com `Cache-Control: max-age=600` e um
`Age` independente por arquivo, então sem carimbo um visitante que volte dentro dessa
janela pode receber HTML novo com `app.js` antigo — e uma mudança de estrutura como a de
19/09/2026, que trocou os ids do HTML, transforma essa combinação em página em branco.
Aconteceu ao conferir a publicação daquele dia. `monta()` ainda checa se os elementos que
espera existem e, se não existirem, mostra uma frase pedindo recarga em vez de falhar em
silêncio — é a segunda trava.

Não remover o carimbo nem a checagem.

### `docs/styleguide.html`

Folha de estilo viva: paleta, escala tipográfica, controles, hierarquia de traço, cartão
e tooltip, lendo os mesmos `tokens.css` e `style.css` do site. Fora do menu e com
`noindex`. Quem mexer nos tokens confere ali primeiro.

## Convenções de código

- Python 3.11+, `requests`, `pandas`, `pyyaml`, `openpyxl`, `pyarrow`.
- Type hints em funções públicas. Docstrings curtas em português.
- Nenhuma dependência de front além do ECharts via CDN (versão pinada) e das duas
  famílias do Google Fonts. Nenhuma delas pode ser necessária para a página funcionar.
- Testes nunca vão à rede. `tests/test_parsing.py` cobre a normalização da coleta
  (decimal brasileiro, data `dd/MM/yyyy`, payload mascarado, janelas); `tests/test_bases.py`,
  as quatro transformações; `tests/test_derivadas.py`, residual, soma e média ponderada,
  mais a coerência do YAML de produção; `tests/test_resiliencia.py`, a política de falha e
  o guard de regressão.
- `python src/build_dataset.py --do-cache` reconstrói os artefatos a partir do cache
  local, sem rede. É o jeito de iterar no front, na Metodologia ou na planilha sem repetir
  as 108 requisições. Uso manual: no CI a coleta é sempre real.

## O que exige decisão humana — sinalizar, não executar

- Publicar o repositório (o job `publica` só roda com a variável de repositório
  `PUBLICAR_PAGES=true`, ligada desde 30/08/2026). O *go live* da página foi autorizado
  em 19/09/2026; desligar a publicação de novo também é decisão humana.
- Reintroduzir qualquer atribuição institucional — nome, sigla, assinatura ou marca.
- Incluir série cuja metodologia não esteja documentada em fonte oficial.
- Construir indicador derivado (ex.: proxy de alavancagem) sem nota metodológica escrita.
- Alterar a paleta ou a tipografia de `docs/tokens.css`.
- Implementar variação (mensal ou em 12 meses) para séries já em porcentagem.
- Escrever à mão qualquer seção da aba Metodologia que hoje é gerada do catálogo.
