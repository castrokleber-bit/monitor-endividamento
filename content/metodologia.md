# Nota metodológica

*Documento vivo. Toda série incluída no monitor precisa de um parágrafo aqui.*

## Abrangência das fontes

**Banco Central do Brasil (SGS).** Cobre exclusivamente operações do Sistema Financeiro
Nacional. Não inclui dívida das famílias com o comércio, com fintechs não reguladas nem
dívida das empresas captada no mercado de capitais ou no exterior.

**BIS (via FRED).** Cobre crédito ao setor de todas as fontes — bancos domésticos, mercado
de capitais e credores externos. Por isso os níveis são estruturalmente mais altos que os
do SFN e **não são comparáveis** com o bloco Brasil.

## Definições

**Endividamento das famílias** (SGS 29037). Relação entre o saldo das dívidas das famílias
com o SFN e a renda acumulada nos últimos doze meses.

**Endividamento exceto crédito habitacional** (SGS 29038). Mesma razão, com o mesmo
denominador de renda, retirando o crédito habitacional do numerador. A distância entre as
duas curvas é, por construção, a parcela habitacional do endividamento. O painel exibe as
duas porque o crédito habitacional tem prazo e garantia distintos do restante da carteira;
nenhuma das duas é derivada da outra pelo pipeline — as duas vêm prontas da fonte.

**Comprometimento de renda** (SGS 29034, com ajuste sazonal; 29265, sem ajuste). Relação
entre os pagamentos esperados para o serviço da dívida com o SFN e a renda mensal das
famílias, em média móvel trimestral. As duas séries medem o mesmo conceito e são divulgadas
separadamente pela fonte: a série com ajuste sazonal é a principal do painel, e a sem
ajuste aparece ao lado para tornar visível o componente sazonal. O pipeline não aplica nem
remove ajuste sazonal em série nenhuma.

**Inadimplência.** Percentual da carteira com atraso superior a 90 dias, para pessoas
físicas (SGS 21084) e pessoas jurídicas (SGS 21083). O total do SFN
(SGS 21082) não é a média simples de pessoas físicas e jurídicas: é ponderado pelo peso
de cada carteira, e por isso fica entre as duas curvas, mais próximo daquela que tem
maior saldo.

**Aberturas da inadimplência de pessoas físicas** (SGS 21112 e 21113). A série 21112 cobre
apenas as operações com **recursos livres** — não inclui o crédito direcionado (habitacional,
rural e demais linhas com destinação e taxa reguladas), que está dentro do total de pessoas
físicas (21084). Os dois recortes têm carteiras diferentes, então os níveis não são
comparáveis entre si. A série 21113 é uma modalidade dentro de 21112, o cheque especial.

**Saldo da carteira de crédito.** Estoque de operações de crédito do SFN, em R$ milhões
correntes, como divulgado pela fonte — sem deflacionamento e sem ajuste sazonal. O total
(SGS 20539) corresponde à soma de pessoas jurídicas (20540) e pessoas físicas (20541); as
três séries são arredondadas de forma independente na fonte, então a soma das aberturas
pode divergir do total em até R$ 2 milhões em um mês — diferença de arredondamento, não de
conceito. O total começa em junho de 1988 e as aberturas por tomador, em março de 2007.
Parte do crescimento nominal do saldo é inflação; para leitura de alavancagem, usar as
séries em proporção do PIB (20622, 20623, 20624).

**Saldo a preços constantes** (todas as séries terminadas em `_real`: os três saldos da
carteira, os dois saldos de pessoas jurídicas por origem dos recursos e os dois de capital
de giro por prazo). Não vêm da fonte: são calculadas no pipeline, e o deflacionamento é a
única operação de cálculo do monitor. O saldo nominal de cada mês é deflacionado pelo IPCA e
expresso a preços do mês mais recente do índice. O deflator é a variação mensal do IPCA
(SGS 433), encadeada em um índice de preços — `I(t) = I(t-1) × (1 + variação/100)` —, e o
valor real é `nominal(t) × I(base) / I(t)`, com a base no último mês de IPCA divulgado.
A base é móvel: a cada atualização os valores passam a estar a preços do mês mais recente,
e a unidade da série registra qual é esse mês. Mês de saldo sem IPCA correspondente fica
de fora da série real — nada é extrapolado. Como o índice é encadeado a partir das
variações mensais publicadas, que a fonte arredonda em duas casas, o nível pode diferir
marginalmente do número-índice do IPCA calculado pelo IBGE. As séries nominais originais
seguem inteiras em `data/` e na planilha.

**Crédito em proporção do PIB** (SGS 20622 total, 20623 pessoas jurídicas, 20624 pessoas
físicas). Razão entre o saldo da carteira e o PIB, calculada e divulgada pela própria
fonte. O pipeline não a recalcula nem escolhe o denominador: coleta a série pronta, como
qualquer outra. Vale aqui a mesma ressalva do saldo — arredondamento independente faz a
soma das aberturas divergir do total em até 0,01 ponto percentual —, e também o descompasso
de início: o total começa em julho de 1995 e as aberturas, em março de 2007.

**Crédito livre e crédito direcionado às pessoas jurídicas** (SGS 20543 recursos livres,
20594 recursos direcionados). Recursos livres são as operações de crédito com taxa de juros
livremente pactuada entre a empresa e a instituição financeira. Recursos direcionados são
as operações com destinação e taxa reguladas — crédito rural, imobiliário, e as lastreadas
em recursos do BNDES ou em recursos compulsórios e governamentais. As duas séries somam o
saldo da carteira de pessoas jurídicas (20540): na observação de julho de 2026,
R$ 1.590.492 milhões mais R$ 1.141.022 milhões contra um total de R$ 2.731.513 milhões, com
diferença de R$ 1 milhão por arredondamento independente na fonte. Ambas começam em março
de 2007.

**Capital de giro por prazo de contratação** (SGS 20547 até 365 dias, 20548 acima de 365
dias). Capital de giro é uma modalidade **dentro** dos recursos livres às pessoas jurídicas
(20543), não um recorte do crédito às empresas como um todo — os níveis não são comparáveis
com os do gráfico anterior. As duas séries também não esgotam a modalidade: a fonte publica
ainda o capital de giro rotativo (20549), que não entra no painel, e a soma das três é que
corresponde ao capital de giro total (20550). Em julho de 2026, R$ 92.537 milhões mais
R$ 382.840 milhões mais R$ 14.543 milhões contra um total de R$ 489.919 milhões. As duas
séries por prazo começam em março de 2011, quando a fonte passou a publicar a abertura.

**Composição do comprometimento.** As séries de juros (SGS 29033) e de amortização
(SGS 29036), ambas com ajuste sazonal, somam exatamente o comprometimento com o serviço
da dívida (SGS 29034). Não confundir 29033 com 29035, que é o comprometimento com o
serviço da dívida **exceto crédito habitacional** — outra decomposição.

## Séries internacionais (BIS, via FRED)

**Crédito às famílias e às ISFLSF, % do PIB** (`QBRHAM770A`, `QUSHAM770A`, `QMXHAM770A`,
`QCLHAM770A`). Crédito total às famílias e às instituições sem fins lucrativos a serviço
das famílias, de todas as fontes credoras, ajustado por quebras de série, em percentual do
PIB. Trimestral.

**Crédito às empresas não financeiras, % do PIB** (`QBRNAM770A`, `QUSNAM770A`,
`QMXNAM770A`, `QCLNAM770A`). Mesma definição, para o setor de empresas não financeiras.
Trimestral.

**Crédito ao setor privado não financeiro, % do PIB** (`QBRPAM770A`). Soma dos dois
setores acima para o Brasil, na definição do BIS. As três séries são divulgadas
arredondadas de forma independente, então a soma das componentes pode divergir do total
em até 0,5 ponto percentual em um trimestre — diferença de arredondamento na fonte, não
de conceito.

Em 30/08/2026 saíram do monitor quatro séries do Federal Reserve que descreviam apenas os
Estados Unidos, sem contraparte brasileira: serviço da dívida e obrigações financeiras das
famílias (`TDSP` e `FODSP`) e inadimplência de cartão e de empresas nos bancos comerciais
(`DRCCLACBS` e `DRBLACBS`). Os dois gráficos que as exibiam foram retirados e as séries
deixaram de ser coletadas — não estão mais em `data/` nem na planilha. O bloco
internacional ficou restrito ao que é comparável com o Brasil, nas séries do BIS.

## Tratamento dos valores na coleta

Nenhum valor é interpolado, arredondado ou estimado em `data/`. Observação sem valor
divulgado é omitida: string vazia no SGS, ponto (`.`) no FRED.

O SGS não é consistente no separador decimal entre séries. A regra aplicada em
`src/fetch_bcb.py` é determinística: havendo vírgula, a vírgula é o decimal e o ponto é
separador de milhar; sem vírgula, o ponto só é tratado como milhar quando forma grupos de
exatamente três dígitos; nos demais casos o ponto é o separador decimal.

O painel exibe duas casas decimais nos valores percentuais e nenhuma nos valores em
R$ milhões, e reduz a precisão dos rótulos do eixo. Isso é formatação de exibição: o
valor da fonte segue íntegro no parquet, no JSON, na planilha e no CSV de cada gráfico.

## Indicadores derivados

O monitor tem uma única operação de cálculo: o deflacionamento do saldo da carteira de
crédito pelo IPCA, descrito acima em *Saldo a preços constantes*. A regra vive em
`config/derivadas.yaml` e a implementação, em `src/derivadas.py`. Toda série calculada
aparece na página com a linha de procedência trocada — em vez do código na fonte, a
descrição do cálculo — para que não seja confundida com valor divulgado pelo BCB.

Nenhum outro indicador derivado entra no painel sem regra em `config/` e parágrafo aqui.

## Defasagem de divulgação

Os indicadores de endividamento e comprometimento de renda são publicados pelo BCB em até
oito semanas após o mês de referência. As séries do BIS têm defasagem de um a dois
trimestres. O painel exibe a data da última observação de cada série.
