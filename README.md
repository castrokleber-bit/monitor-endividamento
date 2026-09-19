# Monitor de Crédito e Endividamento

Painel com o estoque de crédito, a inadimplência, o endividamento e o comprometimento de
renda de famílias e empresas não financeiras. Dados oficiais, atualização automática
quinzenal e download em XLSX.

Kleber Pacheco de Castro

> **Atribuição institucional suspensa.** Enquanto não houver validação institucional, o
> painel não faz menção a nenhuma entidade — nem no rodapé, nem na planilha, nem nos nomes
> dos tokens de cor. Os créditos ficam com o autor. Ver "Publicação", abaixo.

## Estado do projeto

ETL e front rodando ponta a ponta: **108 séries** (94 do BCB/SGS, 9 do FRED/BIS, 5
calculadas) e **20 gráficos em 5 abas** — Mercado de crédito, Inadimplência, Dívida das
famílias, Comparação internacional e Metodologia.

### Reformulação de 19/09/2026

A página foi reconstruída sobre o catálogo G1–G20 descrito na orientação de 18/09/2026.

**Seletor de base por gráfico.** Cinco maneiras de exibir um saldo, calculadas no
pipeline (`src/transformacoes.py`) e declaradas por série no campo `bases`:

| base | sufixo | regra |
|---|---|---|
| R$ correntes | `_nominal` | valor da fonte na unidade de exibição (R$ bilhões) |
| R$ constantes | `_real` | deflacionado pelo IPCA (433), a preços do mês mais recente do índice |
| % do PIB | `_pib` | dividido pelo PIB acumulado em 12 meses (4382) |
| Variação mensal | `_var1m` | contra o mês anterior, sobre o valor nominal |
| Variação em 12 meses | `_var12m` | contra o mesmo mês do ano anterior, sobre o valor nominal |

As duas variações são calculadas sobre o valor nominal — variação de série deflacionada
descontaria a inflação duas vezes — e **nenhuma é dessazonalizada**. A mensal é a que
mais sofre com isso, e a Metodologia avisa. A comparação é sempre por data de calendário,
nunca por posição na lista: série com mês faltando não compara o mês errado.

Séries já em porcentagem não têm seletor: taxa não se deflaciona nem se divide pelo PIB.
A variação em pontos percentuais para essas séries está prevista no catálogo e não
implementada, por decisão.

**Seletor de período.** Tudo / 10 / 5 / 3 / 1 ano, mais intervalo personalizado em dois
campos mês/ano. Um seletor por gráfico e um por aba; o da aba sobrescreve os individuais.
O recorte fixo a partir de 2005 deixou de existir — por padrão cada gráfico mostra a série
completa (ver `inicio: comum` em `config/abas.yaml` para o único caso em que isso é
limitado, e por quê).

**Aba Metodologia gerada do catálogo.** As explicações saíram dos cartões; cada gráfico
tem um ícone "i" que leva à âncora certa. Fontes, transformações, séries derivadas, ficha
de série e histórico de atualizações são produzidos por `src/build_metodologia.py` a cada
build. O texto corrido continua humano, em `content/metodologia.md`.

**O filtro Família / Empresas / Ambos saiu**, substituído por gráficos específicos. O
campo `segmento` continua obrigatório no catálogo e virou metadado da ficha de série.

### Validações que o build faz contra a fonte

`build_dataset.py` sai com **código 1** se qualquer uma falhar:

| verificação | resultado em 19/09/2026 |
|---|---|
| parcela residual fecha no total publicado | exato, a menos de erro de ponto flutuante |
| % do PIB calculado reproduz o % do PIB oficial do BCB | ≤ 0,005 pp em 6 pares de séries |
| gráfico citando série inexistente no catálogo | — |
| base pedida por um gráfico e não declarada pela série | — |
| série em gráfico sem `segmento` | — |
| série do Brasil fora da primeira posição (identidade visual) | — |

Identidades conferidas na construção do catálogo, todas passando: G1/G2/G3 (partes =
total, exato); G4–G7 (≤ 0,0007%, arredondamento da fonte); os dezesseis subsetores somando
a indústria (exato); e as tabelas 23 e 24 do BCB fechando entre si com diferença máxima de
R$ 5 milhões sobre R$ 2,7 trilhões.

### Totais que o BCB não publica

As tabelas 23 (porte) e 24 (atividade econômica) não têm código de "Total" no SGS —
varridos 22020–22026, 22045–22055 e 27695–27710 sem encontrar. Os totais são calculados em
`config/derivadas.yaml` (`soma` para os saldos, `media_ponderada` para a inadimplência) e
validados por cruzamento entre as duas tabelas. A fórmula da média ponderada foi verificada
onde existe série oficial para comparar: ponderando 21083 e 21084 pelos saldos 20540 e
20541, o resultado reproduz o total oficial 21082 com diferença de 0,004 pp.

### Séries coletadas sem gráfico

Seguem no catálogo, no parquet e na aba "Referência" da planilha: os % do PIB oficiais do
BCB (usados como padrão-ouro do teste automático), as taxas médias de juros, as aberturas
do comprometimento de renda e a inadimplência do cheque especial — todas retiradas do
painel em 19/09/2026, quando a página passou a seguir só o catálogo G1–G20. Mais o IPCA
(433) e o PIB acumulado em 12 meses (4382), que são insumo das transformações.

## Ordem de execução

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export FRED_API_KEY=...            # https://fredaccount.stlouisfed.org/apikeys
                                   # ou grave em .env na raiz (fora do versionamento)

python -m unittest discover -s tests   # transformações, sem rede
python src/validate_series.py      # PRIMEIRO PASSO. Confere todo código contra a API.
python src/build_dataset.py        # coleta, deriva, transforma, gera data/ e docs/dados.js
python src/build_xlsx.py           # gera a planilha em data/ e copia para docs/
python -m http.server -d docs      # abre o painel em localhost:8000

# Iterar no front sem repetir as 108 requisições:
python src/build_dataset.py --do-cache
```

O painel também abre com duplo clique em `docs/index.html`, por `file://`. É por isso
que os dados são publicados como `docs/dados.js` (`window.MONITOR = {...}`) e não como
JSON lido por `fetch()`: sob `file://` o navegador bloqueia `fetch()` de arquivo local.

## Artefatos gerados

| arquivo | conteúdo |
|---|---|
| `data/series.parquet` | formato longo canônico, uma linha por observação |
| `data/series.json` | o mesmo formato longo em JSON colunar — `pandas.DataFrame(payload["dados"])` |
| `data/manifest.json` | procedência e frescor de cada série (`ok`, `stale` ou `ausente`) |
| `data/historico.json` | o que mudou a cada execução — alimenta a aba Metodologia |
| `data/estado.json` | última coleta boa, mês-base do deflator, vintage do PIB, próxima coleta |
| `data/_cache/` | último payload por série, fora do versionamento |
| `docs/dados.js` | payload embutido que a página consome |
| `docs/monitor_endividamento.xlsx` | planilha pública (cópia de `data/`) |

`validate_series.py` sai com código 1 se qualquer série falhar. O workflow do GitHub Actions
usa isso como gate: dado não sobe se um código estiver quebrado.

## Política de falha na coleta

Uma série problemática nunca derruba a coleta das outras:

| situação | `status` no manifesto | efeito |
|---|---|---|
| coleta nova bem-sucedida | `ok` | — |
| fonte caiu, há cache | `stale` | reusa o cache; `ultima_coleta_ok` diz de quando é o dado |
| fonte caiu, sem cache | `ausente` | a série fica fora dos artefatos daquela execução |

Os artefatos são sempre escritos. O que protege a publicação é o **guard de regressão**:
se uma série que tinha dado na execução anterior desaparece, ou se a cobertura total cai,
`build_dataset.py` escreve tudo e sai com **código 2**, e o workflow para antes do commit —
um dia ruim não publica cobertura menor. Perda de observações dentro de uma série que
continua presente é só aviso, porque revisão da fonte pode encurtar série legitimamente.
Para publicar mesmo assim, quando a perda é esperada, use `--sem-guard`.

Códigos de saída do `build_dataset.py`: `0` ok · `1` configuração inconsistente
(`abas.yaml` citando série que não existe, ou série sem `segmento`) · `2` regressão de
cobertura.

## Publicação

A página está no ar em <https://castrokleber-bit.github.io/monitor-endividamento/>,
publicada por decisão de 19/09/2026. A variável `PUBLICAR_PAGES` já estava ligada desde
30/08/2026 e *Pages → Source* já estava em *GitHub Actions*.

O job `publica` do workflow só roda se existir a variável de repositório
`PUBLICAR_PAGES` com valor `true`. Ligar ou desligar a publicação é, por construção, um
ato explícito nas configurações do repositório — não uma edição de arquivo — para que a
decisão fique registrada e visível:

1. *Settings → Secrets and variables → Actions → Variables* → `PUBLICAR_PAGES` = `true`
2. *Settings → Pages → Source: GitHub Actions*

## Atualização

Quinzenal, pelo cron do GitHub Actions nos dias **1 e 16** às 21:00 UTC (18:00 de
Brasília), mais `workflow_dispatch` para forçar após uma divulgação. Se a coleta falhar, o
job para antes do commit — nada de dado parcial — e abre (ou comenta em) uma issue
rotulada `pipeline`.

## Antes de publicar

- [x] `config/_validacao.json` sem falhas. O nome oficial não é conferido contra a API:
      o SGS não expõe metadados por código (ver CLAUDE.md). Quem valida o código são as
      identidades contábeis do build, que são teste mais forte que um nome
- [x] `content/metodologia.md` com um parágrafo por série incluída — as séries do
      catálogo aparecem citadas pelo código na fonte
- [x] `FRED_API_KEY` cadastrada como GitHub Secret (nunca no repositório) — é o que o
      workflow usa, via `secrets.FRED_API_KEY`
- [ ] **Apagar a variável de repositório `FRED_API_KEY`.** Além do Secret, existe uma
      *variável* de mesmo nome com a chave em texto claro, criada em 30/08/2026. Variável
      de Actions não é criptografada e a própria documentação do GitHub diz para não
      guardar segredo nela; ela não é legível sem autenticação, mas é visível a qualquer
      colaborador e a qualquer workflow do repositório. O workflow não a usa. Rotacionar
      a chave no FRED e apagar a variável em *Settings → Secrets and variables → Actions
      → Variables*
- [ ] ~~Rotacionar a chave do FRED antes de tornar o repositório público~~ — o
      repositório já é público; ver o item acima
- [ ] Se a atribuição institucional for retomada, validá-la com quem de direito antes de
      voltar a citar qualquer entidade na página, na planilha e nos tokens de cor

Sugestão: manter o repositório privado durante o desenvolvimento e torná-lo público apenas
no go live.
