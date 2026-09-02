# Monitor de Endividamento

Painel com as trajetórias de endividamento, inadimplência, comprometimento de renda
e alavancagem de famílias e empresas não financeiras. Dados oficiais, atualização automática
diária e download em XLSX.

Kleber Pacheco de Castro

> **Atribuição institucional suspensa.** Enquanto não houver validação institucional, o
> painel não faz menção a nenhuma entidade — nem no rodapé, nem na planilha, nem nos nomes
> dos tokens de cor. Os créditos ficam com o autor. Ver "Publicação", abaixo.

## Estado do projeto

ETL e front construídos e rodando ponta a ponta: 38 séries (22 do BCB/SGS, 9 do FRED/BIS,
7 calculadas), 12 gráficos em 5 blocos. `build_dataset.py` falha se `blocos.yaml` citar
série inexistente.

Em 02/09/2026 entrou o bloco *Empresas — composição do crédito*, com dois gráficos: crédito
livre contra crédito direcionado a pessoas jurídicas (SGS 20543 e 20594) e capital de giro
por prazo de contratação (SGS 20547 e 20548). Os quatro saldos são coletados em valores
nominais e exibidos a preços constantes, como os demais saldos do painel. Na mesma data a
página passou a dispor os gráficos em duas colunas.

Em 30/08/2026 saíram do catálogo as quatro séries do FRED que só descreviam os Estados
Unidos (`TDSP`, `FODSP`, `DRCCLACBS`, `DRBLACBS`), junto com os dois gráficos que as
exibiam. A única série coletada sem gráfico é o IPCA (SGS 433), que entra como deflator.

Séries ainda não incluídas no catálogo estão listadas ao final de `config/series_bcb.yaml`
(custo médio do crédito PJ, concessões, prazo médio). Cada uma exige localizar o código no
SGS e escrever a nota metodológica antes de entrar.

Os gráficos são recortados a partir de 2005 (`recorte.inicio` em `config/blocos.yaml`).
O recorte é só de exibição — `data/` e a planilha mantêm cada série inteira.

## Séries calculadas

`config/derivadas.yaml` declara as séries que não vêm da fonte, e `src/derivadas.py` as
calcula dentro do `build_dataset.py`, depois da coleta. Hoje há uma só operação: o saldo
da carteira de crédito deflacionado pelo IPCA (SGS 433), a preços do mês mais recente do
índice. A base é móvel — acompanha o último IPCA divulgado — e a unidade de cada série
diz qual é o mês (`R$ milhões de jul/2026`). Nos gráficos, `{base_ipca}` na unidade
declarada em `blocos.yaml` é substituído por esse mês no build.

As séries nominais continuam publicadas ao lado das calculadas. Na página, série
calculada troca a linha de procedência pela descrição do cálculo, para não ser confundida
com valor divulgado pela fonte. A regra está escrita em `content/metodologia.md`; nenhuma
outra série derivada entra sem esse par de YAML e nota.

## Ordem de execução

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export FRED_API_KEY=...            # https://fredaccount.stlouisfed.org/apikeys
                                   # ou grave em .env na raiz (fora do versionamento)

python -m unittest discover -s tests   # transformações, sem rede
python src/validate_series.py      # PRIMEIRO PASSO. Confere todo código contra a API.
python src/build_dataset.py        # coleta, normaliza, gera data/ e docs/dados.js
python src/build_xlsx.py           # gera a planilha em data/ e copia para docs/
python -m http.server -d docs      # abre o painel em localhost:8000
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
(`blocos.yaml` citando série que não existe) · `2` regressão de cobertura.

## Publicação

O job `publica` do workflow está **desligado por padrão**: ele só roda se existir a
variável de repositório `PUBLICAR_PAGES` com valor `true`. A coleta diária e o commit
dos dados seguem funcionando normalmente com a publicação desligada.

Ligar a publicação é, por construção, um ato explícito nas configurações do repositório
— não uma edição de arquivo — para que a decisão de go live fique registrada e visível:

1. *Settings → Secrets and variables → Actions → Variables* → `PUBLICAR_PAGES` = `true`
2. *Settings → Pages → Source: GitHub Actions*

## Antes de publicar

- [ ] `config/_validacao.json` sem falhas e com os nomes oficiais conferidos manualmente
- [x] `content/metodologia.md` com um parágrafo por série incluída — as 30 séries do
      catálogo aparecem citadas pelo código na fonte
- [x] `FRED_API_KEY` cadastrada como GitHub Secret (nunca no repositório)
- [ ] Rotacionar a chave do FRED antes de tornar o repositório público
- [ ] Se a atribuição institucional for retomada, validá-la com quem de direito antes de
      voltar a citar qualquer entidade na página, na planilha e nos tokens de cor

Sugestão: manter o repositório privado durante o desenvolvimento e torná-lo público apenas
no go live.
