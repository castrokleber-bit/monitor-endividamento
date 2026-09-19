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
- `406` = série inexistente ou parâmetro inválido. `429` = rajada. Usar retry com backoff
  exponencial e intervalo mínimo entre chamadas.
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

| token | valor | uso |
|---|---|---|
| `--azul` | `#164194` | títulos, série principal Brasil |
| `--ciano` | `#008BD2` | série secundária, destaques |
| `--cinza` | `#595959` | texto corrido, eixos |
| `--cinza-claro` | `#D9D9D9` | grid, bordas |
| `--fundo` | `#FFFFFF` | fundo da página |

Tipografia: **Arial** em toda a página (`font-family: Arial, Helvetica, sans-serif`).

Paleta das linhas dos gráficos, na ordem de uso obrigatória (Brasil sempre na primeira):

| token | valor | |
|---|---|---|
| `--serie-1` | `#164194` | azul institucional |
| `--serie-2` | `#008BD2` | ciano institucional |
| `--serie-3` | `#00785F` | verde-petróleo |
| `--serie-4` | `#C77F00` | ocre |
| `--serie-5` | `#595959` | cinza |

> **Decisão de 30/08/2026.** Da terceira série em diante a paleta sai da família azul.
> A regra anterior — derivar tudo dos dois azuis — produzia curvas indistinguíveis nos
> gráficos de três e quatro séries e ilegíveis em preto e branco. Não voltar a tons de
> azul nas posições 3 e 4 sem decisão humana. Vermelho segue reservado a alertas.

Cada gráfico traz: título, subtítulo com unidade e período, fonte explícita, data da
última observação e botão de download. Sem sombras, sem gradientes, sem arredondamento
decorativo — o padrão é sóbrio e institucional.

**Layout em duas colunas (decisão de 02/09/2026).** Dentro de uma aba, os gráficos vão
numa grade de duas colunas; um gráfico sozinho na última linha ocupa a largura inteira.
Abaixo de 900px a grade volta a uma coluna. Os cartões de uma mesma linha alinham topo,
subtítulo, área de gráfico e rodapé por `subgrid` — por isso o cartão tem sempre **quatro**
filhos. Quem mexer nessa estrutura em `app.js` precisa manter a contagem, senão as curvas
de dois gráficos vizinhos deixam de ficar na mesma altura. (Os campos do intervalo
personalizado ficam dentro do topo, e não como quinto filho, justamente por isso: eles
aparecem e somem conforme o leitor escolhe "Personalizado…".)

**Reformulação de 19/09/2026.** A página foi reorganizada em cinco abas — Mercado de
crédito, Inadimplência, Dívida das famílias, Comparação internacional e Metodologia — com
o catálogo de gráficos G1 a G20 declarado em `config/abas.yaml`. O que mudou, e não deve
ser desfeito sem nova decisão humana:

- **O recorte fixo de exibição a partir de 2005 acabou.** Cada gráfico abre na série
  completa e o leitor escolhe o intervalo: atalhos Tudo / 10 / 5 / 3 / 1 ano, mais um
  intervalo personalizado em dois campos mês/ano. Há um seletor por gráfico e um por aba,
  e o da aba sobrescreve os individuais quando acionado.
- **O filtro Família / Empresas / Ambos saiu.** O recorte por tomador passou a ser feito
  por gráficos específicos. O campo `segmento` do catálogo continua obrigatório em toda
  série — `build_dataset.py` falha sem ele —, mas agora é metadado da ficha de série na
  aba Metodologia, não filtro.
- **As explicações saíram dos cartões.** O cartão carrega título, unidade no eixo,
  legenda, procedência, último ponto e um ícone "i" que leva à âncora correspondente na
  aba Metodologia. Nenhuma nota de rodapé dentro do cartão.
- **A aba Metodologia é gerada do catálogo.** Fontes, transformações, séries derivadas,
  ficha por série e histórico de atualizações são produzidos por `src/build_metodologia.py`
  a cada build e encaixados nos marcadores `{{fontes}}`, `{{transformacoes}}`,
  `{{derivadas}}`, `{{ficha}}` e `{{historico}}` de `content/metodologia.md`. O texto
  corrido continua sendo humano. Não escrever à mão o que é gerado: desatualiza.
- **A atualização passou de diária a quinzenal**, dias 1 e 16.

**Onde o intervalo "Tudo" começa.** Por `inicio: comum` (padrão em `config/abas.yaml`),
um gráfico abre na primeira data em que TODAS as suas séries têm observação. A alternativa
`uniao` existe mas não é o padrão por um caso concreto: a série 20539 (total do SFN) tem
observações desde 06/1988, mas todas as suas aberturas começam em 03/2007, e os valores
anteriores a 1994 estão reexpressos em reais a ponto de serem degenerados (06/1988 = R$ 0).
Com `uniao`, G4 e G5 abririam numa linha reta no zero por vinte anos. O recorte é só de
exibição — `data/`, a planilha e o CSV de cada gráfico seguem com a série inteira.

**Cor por posição, não por identidade.** O front atribui cor pela ordem da série no
gráfico. A consistência que a orientação pede — mesma cor para PJ, PF, livre e direcionado
em todos os gráficos em que aparecem — se cumpre pela ORDENAÇÃO em `abas.yaml`: o agregado
sempre primeiro, depois PJ antes de PF e direcionado antes de livre. Quem reordenar um
gráfico quebra a consistência entre gráficos. Séries com `papel: total` recebem traço mais
grosso.

Quando um gráfico tem mais séries que cores (G8 tem oito, a abertura da indústria em G16
tem dezessete), `app.js` varia o TRAÇO — sólido, tracejado, pontilhado — em vez de
estender a paleta. Estender a paleta é inventar cor institucional e depende de decisão
humana. Acima de seis séries a legenda vira `scroll`, de uma linha só: com dezessete
curvas ela ocupava cinco linhas e invadia o eixo do tempo.

**"Detalhar indústria" troca o gráfico, não acrescenta séries.** Ligar o detalhe em G16
mostra SÓ as dezesseis aberturas da indústria — nem as demais atividades, nem o total da
própria indústria (decisão de 19/09/2026). Acrescentar não funcionava: com o total em
R$ 2,7 trilhões no mesmo eixo, aberturas de R$ 11 a R$ 259 bilhões viravam uma faixa
colada no zero; e manter o total da indústria, quatro vezes maior que a maior abertura,
reproduzia o problema em escala menor.

## Convenções de código

- Python 3.11+, `requests`, `pandas`, `pyyaml`, `openpyxl`, `pyarrow`.
- Type hints em funções públicas. Docstrings curtas em português.
- Nenhuma dependência de front além do ECharts via CDN (versão pinada).
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
- Estender a paleta de cores além dos cinco tokens.
- Implementar variação (mensal ou em 12 meses) para séries já em porcentagem.
- Escrever à mão qualquer seção da aba Metodologia que hoje é gerada do catálogo.
