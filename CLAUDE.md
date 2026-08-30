# Monitor de Endividamento

Painel público com as trajetórias de endividamento, inadimplência, comprometimento
de renda e alavancagem de **famílias** e **empresas não financeiras**, no Brasil e em
benchmark internacional. Dados atualizados automaticamente via API e baixáveis em XLSX.

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
config/     catálogo de séries (YAML) — fonte única da verdade
src/        ETL determinístico em Python
data/       artefatos gerados e versionados (parquet, json, xlsx, manifest)
content/    textos humanos (notas metodológicas)
docs/       GitHub Pages (index.html, app.js, style.css)
tests/      testes das transformações
```

Fluxo: `validate_series.py` → `fetch_*.py` → `build_dataset.py` → `build_xlsx.py` → commit.

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

Nunca converter unidade sem registrar a regra em `config/` e em `content/metodologia.md`.

## Armadilhas conhecidas das APIs

**BCB / SGS** (`https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json`)

- Recusa intervalos maiores que **10 anos** em séries diárias — paginar por janelas.
- Datas vêm como `dd/MM/yyyy` (string). Valores vêm como string; em algumas séries o
  separador decimal é vírgula. Sempre `.replace(".", "").replace(",", ".")` antes do cast.
- `406` = série inexistente ou parâmetro inválido. `429` = rajada. Usar retry com backoff
  exponencial e intervalo mínimo entre chamadas.
- Resposta pode vir como HTML de erro com status 200. Validar que o payload é lista de dicts.

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
Para gráficos com mais de duas séries, derivar a paleta dos dois azuis institucionais
antes de introduzir qualquer cor nova; vermelho fica reservado para alertas.

Cada gráfico traz: título, subtítulo com unidade e período, fonte explícita, data da
última observação e botão de download. Sem sombras, sem gradientes, sem arredondamento
decorativo — o padrão é sóbrio e institucional.

## Convenções de código

- Python 3.11+, `requests`, `pandas`, `pyyaml`, `openpyxl`, `pyarrow`.
- Type hints em funções públicas. Docstrings curtas em português.
- Nenhuma dependência de front além do ECharts via CDN (versão pinada).
- Testes cobrem as transformações (parsing de data, decimal brasileiro, alinhamento de
  periodicidade), não as chamadas de rede.

## O que exige decisão humana — sinalizar, não executar

- Publicar o repositório ou a página (o *go live* depende de decisão humana; o job
  `publica` só roda com a variável de repositório `PUBLICAR_PAGES=true`).
- Reintroduzir qualquer atribuição institucional — nome, sigla, assinatura ou marca.
- Incluir série cuja metodologia não esteja documentada em fonte oficial.
- Construir indicador derivado (ex.: proxy de alavancagem) sem nota metodológica escrita.
