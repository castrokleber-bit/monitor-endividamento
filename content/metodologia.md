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

**Endividamento das famílias.** Relação entre o saldo das dívidas das famílias com o SFN e
a renda acumulada nos últimos doze meses.

**Comprometimento de renda.** Relação entre os pagamentos esperados para o serviço da
dívida com o SFN e a renda mensal das famílias, em média móvel trimestral. A série
principal é ajustada sazonalmente.

**Inadimplência.** Percentual da carteira com atraso superior a 90 dias. O total do SFN
(SGS 21082) não é a média simples de pessoas físicas e jurídicas: é ponderado pelo peso
de cada carteira, e por isso fica entre as duas curvas, mais próximo daquela que tem
maior saldo.

**Saldo da carteira de crédito.** Estoque de operações de crédito do SFN, em R$ milhões
correntes, como divulgado pela fonte — sem deflacionamento e sem ajuste sazonal. O total
(SGS 20539) é a soma exata de pessoas jurídicas (20540) e pessoas físicas (20541). Parte
do crescimento nominal do saldo é inflação; para leitura de alavancagem, usar as séries
em proporção do PIB (20622, 20623, 20624).

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

**Household Debt Service Ratio** (`TDSP`) e **Financial Obligations Ratio** (`FODSP`),
do Federal Reserve. Pagamentos do serviço da dívida das famílias americanas como
percentual da renda pessoal disponível — o espelho conceitual mais próximo do
comprometimento de renda do BCB, ainda que com metodologias distintas. `FODSP` foi
**descontinuada pela fonte**, com última observação em julho de 2023.

**Delinquency rates** (`DRCCLACBS`, cartão de crédito; `DRBLACBS`, empresas), do Federal
Reserve. Percentual da carteira em atraso nos bancos comerciais americanos. O critério de
atraso não é o mesmo do BCB — comparar trajetória, não nível.

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

*(Preencher quando o proxy de alavancagem das empresas for construído. Nenhum indicador
derivado entra no painel sem esta seção escrita e revisada.)*

## Defasagem de divulgação

Os indicadores de endividamento e comprometimento de renda são publicados pelo BCB em até
oito semanas após o mês de referência. As séries do BIS têm defasagem de um a dois
trimestres. O painel exibe a data da última observação de cada série.
