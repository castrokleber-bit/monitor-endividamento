# Metodologia e metadados

*As tabelas desta página — fontes, transformações, séries derivadas, ficha de série e
histórico de atualizações — são geradas automaticamente do catálogo do pipeline a cada
atualização, e por isso descrevem sempre o estado corrente dos dados. O texto corrido é
escrito por pessoas.*

## Sobre o monitor {#sobre}

O Monitor de Endividamento acompanha o estoque de crédito ao setor não financeiro
brasileiro, a inadimplência dessa carteira, e o endividamento e o comprometimento de
renda das famílias, com um recorte de comparação internacional. O escopo é o de famílias
e empresas não financeiras.

É um painel de dados. Apresenta séries públicas e notas metodológicas factuais; não
apresenta leitura, diagnóstico, projeção nem recomendação. Não constitui posição
institucional de nenhuma entidade sobre política monetária, crédito ou regulação
bancária, nem recomendação de investimento.

Autoria: Kleber Pacheco de Castro.

O tratamento dos dados obedece a três regras sem exceção:

- **Nenhum valor é interpolado, extrapolado ou estimado.** Observação que a fonte ainda
  não divulgou é omitida, nunca preenchida.
- **Nenhum arredondamento silencioso.** O valor calculado mantém a precisão do valor de
  origem; o arredondamento existe só na exibição na tela.
- **Toda conversão de unidade está registrada.** A ficha de série abaixo tem uma coluna
  para isso, e nenhuma série é convertida sem ela.

{{fontes}}

## Conceitos

### Crédito ampliado ao setor não financeiro {#conceito-credito-ampliado}

É a medida mais abrangente de dívida que o Banco Central publica. Soma, para o setor não
financeiro residente, os empréstimos tomados junto ao Sistema Financeiro Nacional e a
outras sociedades financeiras, os recursos de fundos governamentais, os títulos de dívida
emitidos — públicos e privados —, os instrumentos securitizados e a dívida contraída no
exterior.

**O total deste conceito inclui o governo.** "Setor não financeiro" abrange governo
geral, empresas não financeiras e famílias. Por isso o total do primeiro gráfico não é a
soma dos gráficos de empresas e de famílias: a diferença é a dívida do setor público. Os
três gráficos são recortes da mesma tabela da fonte, não parcelas um do outro.

A decomposição pode ser conferida nas próprias séries de razão ao PIB publicadas pela
fonte. Em julho de 2026: crédito ampliado às empresas 54,39% do PIB, às famílias 37,83%,
ao governo geral 72,79% — que somam exatamente os 165,01% do total.

A série começa em janeiro de 2013, que é quando a fonte passou a publicá-la.

### Crédito do Sistema Financeiro Nacional {#conceito-credito-sfn}

Saldo da carteira ativa de operações de crédito das instituições financeiras
supervisionadas pelo Banco Central. É um conceito mais estreito que o crédito ampliado:
não inclui títulos de dívida emitidos no mercado de capitais, dívida externa nem recursos
de fundos governamentais que não passem pelo balanço de uma instituição do SFN. Também
não inclui dívida das famílias com o comércio nem com empresas não reguladas.

"Carteira ativa" quer dizer que operações já baixadas para prejuízo saem do saldo. Isso
importa para a leitura da inadimplência: uma operação muito atrasada, ao ser baixada,
deixa de contar tanto no numerador quanto no denominador da taxa.

### Recursos livres e recursos direcionados {#conceito-livre-direcionado}

**Recursos livres** são as operações em que a instituição e o tomador pactuam livremente
taxa, prazo e destinação.

**Recursos direcionados** são as operações cuja destinação e cujas condições são
determinadas por regra — crédito rural, financiamento habitacional, financiamentos com
recursos do BNDES e do FGTS, microcrédito. As taxas são reguladas ou referenciadas a
indexadores definidos em norma.

As duas parcelas somam o saldo total da carteira do SFN. A inadimplência dos recursos
direcionados é estruturalmente mais baixa que a dos livres, sobretudo pela presença de
garantia real no crédito habitacional.

### Modalidades do crédito livre a pessoas jurídicas {#conceito-modalidades-pj}

- **Capital de giro** — financiamento do ciclo operacional da empresa, aberto pela fonte
  entre prazo de até 365 dias e prazo superior a 365 dias. As duas séries não esgotam a
  modalidade: a fonte publica ainda o capital de giro rotativo, de saldo pequeno e
  natureza distinta, que entra na parcela residual deste painel.
- **Desconto de duplicatas e outros recebíveis** — antecipação, pela instituição, de
  valores a receber já contratados pela empresa.
- **Aquisição de veículos** — financiamento de veículos por pessoa jurídica.
- **Financiamento a exportações** — crédito concedido para custeio ou investimento
  vinculado a exportação.
- **Adiantamento sobre contratos de câmbio (ACC)** — antecipação, em reais, do valor de
  uma exportação já contratada mas ainda não embarcada ou não liquidada.

Financiamento a exportações e ACC aparecem como **duas parcelas separadas**, e não
somados numa única linha "Exportações". A decisão é de 19/09/2026 e vale igualmente para
o gráfico de saldo e o de inadimplência: como taxa não é aditiva, somar no saldo e
separar na inadimplência produziria dois gráficos com recortes diferentes sob o mesmo
nome, e a comparação entre eles deixaria de ser direta.

A parcela **Outras modalidades** deste gráfico é um residual calculado. Ver a seção de
séries derivadas e o alerta sobre os dois "Outros".

### Modalidades do crédito livre a pessoas físicas {#conceito-modalidades-pf}

- **Crédito consignado** — crédito pessoal com desconto das parcelas em folha de
  pagamento ou em benefício previdenciário.
- **Crédito não consignado** — crédito pessoal sem esse desconto.
- **Cartão de crédito** — inclui tanto o saldo à vista e parcelado sem juros quanto o
  rotativo e o parcelado com juros.
- **Aquisição de veículos** — financiamento de veículos por pessoa física.

A parcela **Outras modalidades** é um residual calculado e reúne, entre outras,
composição de dívidas, cheque especial, crédito com garantia, aquisição de outros bens,
arrendamento mercantil e desconto de cheques.

O nível de cada modalidade não é comparável linha a linha com o das demais: cheque
especial e rotativo do cartão têm taxas de outra ordem de grandeza e participação pequena
no saldo, enquanto o consignado tem taxa baixa e saldo grande.

### Porte da empresa {#conceito-porte}

A fonte classifica a empresa tomadora pelo porte e publica saldo e inadimplência para
micro, pequenas e médias empresas em conjunto (MPME) e para grandes empresas. O critério
de enquadramento é o do Banco Central, baseado na receita bruta anual declarada.

**Atenção à abrangência.** Esta tabela vem do Sistema de Informações de Créditos (SCR) e
exclui operações com entidades de intermediação financeira. O total dela não coincide com
o total das tabelas de saldo por origem dos recursos e por tipo de tomador. Além disso, a
fonte não publica coluna de total para esta tabela — o total exibido é calculado pelo
pipeline; ver a seção de séries derivadas.

### Atividade econômica {#conceito-atividade}

Abertura do saldo de crédito a pessoas jurídicas pela atividade econômica do tomador,
segundo a CNAE reclassificada pelo Banco Central em quatro grandes grupos —
agropecuária, indústria, serviços e outras atividades — com um segundo nível de detalhe
dentro da indústria.

Mesma base SCR e mesma ressalva de abrangência do recorte por porte. A abertura da
indústria em dezesseis segmentos está disponível no seletor "Detalhar indústria" de cada
gráfico; os dezesseis somam exatamente o total da indústria em todos os meses em que as
séries coexistem.

### Inadimplência {#conceito-inadimplencia}

Parcela da carteira ativa com pelo menos uma parcela em atraso superior a noventa dias,
em porcentagem do saldo daquela carteira. Não inclui operações já baixadas para prejuízo,
que saem da carteira ativa.

**Taxa não é aditiva.** O total não é a soma nem a média simples das aberturas: é a média
ponderada pelo saldo de cada recorte, e por isso fica entre as curvas das aberturas, mais
próximo daquela que tem carteira maior. É também por isso que os gráficos de inadimplência
não têm parcela residual e não têm seletor de base.

### Endividamento das famílias {#conceito-endividamento-familias}

Relação entre o saldo das dívidas das famílias com o Sistema Financeiro Nacional e a
renda acumulada nos últimos doze meses. A série "exceto financiamento imobiliário" usa o
mesmo denominador de renda e retira o crédito habitacional do numerador; a distância
entre as duas curvas é, por construção, a parcela habitacional do endividamento. Nenhuma
das duas é derivada da outra pelo pipeline — as duas vêm prontas da fonte.

### Comprometimento de renda com o serviço da dívida {#conceito-comprometimento}

Relação entre os pagamentos esperados das famílias com o serviço da dívida junto ao SFN —
juros mais amortização, em média móvel trimestral — e a renda mensal das famílias. A
série exibida é a com ajuste sazonal, como a fonte a divulga. O pipeline não aplica nem
remove ajuste sazonal em série nenhuma.

Endividamento e comprometimento têm denominadores diferentes: renda de doze meses num
caso, renda mensal no outro. São dois painéis separados, e não dois eixos no mesmo
gráfico, exatamente por isso — escalas diferentes em eixos duplos produzem leitura errada.

### Séries do BIS {#conceito-bis}

O Bank for International Settlements publica, para um conjunto amplo de países, o crédito
ao setor privado não financeiro em porcentagem do PIB, com metodologia harmonizada que
permite comparação internacional. Chegam aqui pela redistribuição do Federal Reserve Bank
of St. Louis (FRED), são trimestrais e saem com defasagem de um a dois trimestres.

**Os níveis não são comparáveis com as demais abas.** As séries do BIS medem crédito de
todas as fontes — bancos domésticos, mercado de capitais e credores externos —, enquanto
as séries do Banco Central usadas nas outras abas medem apenas o crédito do Sistema
Financeiro Nacional. A abrangência do BIS é estruturalmente mais ampla e os patamares,
mais altos. Comparar um número desta aba com um número de outra é erro de leitura.

Na definição do BIS, o setor privado não financeiro é a soma de famílias e empresas não
financeiras. As três séries são divulgadas com arredondamento independente, então a soma
das duas componentes pode diferir do total em até 0,5 ponto percentual num trimestre.

{{transformacoes}}

{{derivadas}}

## Limitações e alertas {#limitacoes}

### O total do crédito ampliado inclui o governo {#limitacao-amplo-governo}

Já dito acima e repetido aqui porque é o mal-entendido mais provável do painel: o total do
crédito ampliado ao setor não financeiro **não** é a soma do crédito ampliado às empresas
com o crédito ampliado às famílias. A diferença é a dívida do setor público.

### Os dois "Outros" não têm a mesma abrangência {#limitacao-dois-outros}

Nos gráficos de **saldo**, a parcela "Outras modalidades" é um residual calculado pelo
pipeline: total publicado menos a soma das modalidades exibidas. Ela existe para que as
parcelas do gráfico fechem exatamente no total da fonte, e por construção cobre tudo o
que não está nas demais linhas.

Nos gráficos de **inadimplência**, "Outras modalidades" é a série "Outros créditos livres"
publicada pelo próprio Banco Central. Não é um residual — taxa não é aditiva e um resíduo
calculado sobre taxas não teria significado.

**As duas não cobrem o mesmo conjunto de modalidades.** Ler a inadimplência de "Outras
modalidades" como se fosse a inadimplência da parcela residual do gráfico de saldo é erro.

### Totais que diferem entre tabelas da fonte {#limitacao-totais}

As tabelas de saldo e inadimplência por porte da empresa e por atividade econômica vêm do
SCR e excluem operações com entidades de intermediação financeira. Os totais delas são
menores que os das tabelas por origem dos recursos e por tipo de tomador. As duas tabelas
do SCR, por outro lado, fecham entre si: a soma por porte e a soma por atividade econômica
dão o mesmo número, com diferença máxima de R$ 5 milhões sobre um estoque de R$ 2,7
trilhões — o que é o arredondamento independente de cada coluna na fonte.

### Revisões retroativas {#limitacao-revisoes}

O Banco Central revisa dados já divulgados. O pipeline por isso baixa sempre a série
inteira e **substitui** a base local, em vez de apenas acrescentar o mês novo. Quando uma
revisão muda o histórico sem avançar a última observação, o fato fica registrado na
coluna "Revisadas" do histórico de atualizações.

O mês mais recente de várias séries de crédito é preliminar na fonte e pode mudar na
divulgação seguinte.

### Séries curtas e ausência de emenda com a metodologia antiga {#limitacao-inicio}

As séries de crédito ampliado começam em 2013; as de saldo e inadimplência por porte e
por atividade econômica, em 2012; as de inadimplência do SFN, em 2011. Isso torna o
intervalo "Tudo" curto em vários gráficos, e é assim de propósito: **o painel não emenda
essas séries com as da metodologia anterior do Banco Central**, que não são comparáveis.

Um caso merece nota específica. A série de saldo total do SFN tem observações desde junho
de 1988, mas todas as suas aberturas começam em março de 2007, e os valores anteriores a
1994 estão reexpressos em reais a ponto de serem numericamente degenerados — junho de
1988 aparece como R$ 0. Por isso os gráficos que combinam esse total com suas aberturas
abrem na primeira data em que **todas** as séries do gráfico existem, e não na primeira
observação da mais antiga delas. O recorte é apenas de exibição: a planilha de download e
os arquivos em `data/` trazem cada série desde a primeira observação da fonte.

### O que o painel não cobre {#limitacao-cobertura}

Fora do Sistema Financeiro Nacional, o painel não enxerga dívida das famílias com o
comércio, com prestadores de serviço ou com instituições não reguladas, nem dívida de
empresas com fornecedores. Os gráficos de crédito ampliado cobrem parte disso — títulos de
dívida e dívida externa —, mas não o crédito comercial.

O Banco Central não publica, para empresas não financeiras, indicador doméstico
equivalente ao endividamento e ao comprometimento de renda das famílias. A aba de dívida
das famílias, por isso, cobre apenas famílias.

{{ficha}}

{{historico}}
