# Metadados da base — Proj IV

Documento de referência da base congelada em `data/`. O recorte analítico começa no PPI diário (5 jan. 2022) e termina no corte de 21 set. 2026. As demais famílias entram nesse calendário, com defasagem própria de cada fonte.

Este arquivo descreve as fontes, a forma e a periodicidade da coleta, e o dicionário das tabelas no snapshot. O projeto de curso não acessa Postgres, APIs ou credenciais.

## 1. Arquivos do snapshot

| Arquivo | Função | Tabelas |
|---|---|---|
| `data/gas_flare.sqlite` | Base analítica do curso. Export de 27 set. 2026, corte em 21 set. 2026. SHA-256 `155f53607aae0e92e66a588288ce309a8bce05678b77b67a0b56603713db3a6d`. | 14 tabelas de dados (PPI, preços, vendas, finanças, proxies, equity, inflação) e `export_changelog` |
| `data/gas_flare_old.sqlite` | Export anterior, de ago. 2026, corte em 14 ago. 2026. Só para comparação. SHA-256 `61d1766c5055d8fb1f86de2e223aca0b46262bf266dca574e6deb4add85a921f`. | As mesmas 14 tabelas de dados |

O arquivo é imutável para o trabalho de curso. Uma atualização exige novo export a partir do Gas Flare. Não há acesso a Postgres e não há SQLite só de PETR4.

### 1.1 Atualização da base na Etapa 2

A revisão da Etapa 2 conferiu a base contra as fontes e encontrou erros de origem. O pipeline Gas Flare corrigiu esses pontos, e o grupo trocou a base do curso pelo novo export. A tabela `export_changelog` registra cada correção.

| Família | Erro no export anterior | Correção |
|---|---|---|
| PPI (`ppi_daily`) | Leituras de OCR erradas: −13,0 R$/L em 26 jan. 2023, valores em 5 set. 2024 e 18 mar. 2025, e percentuais de três dígitos sem o primeiro algarismo de 11 a 18 set. 2026. | Valores conferidos contra a imagem. Nova regra de validação (seção 2.1). |
| Preço ANP semanal | O diesel era a média de toda linha com "diesel" no nome, com biodiesel B-100 e diesel marítimo. A gasolina incluía a gasolina Premium. A carga contava 22 cópias da linha Brasil, uma por download do arquivo. | Rótulos exatos: Óleo Diesel S-10 e Óleo Diesel S-500; Gasolina A Comum. Uma linha Brasil por produto e semana, do arquivo mais novo. |
| Preço Petrobras semanal | Semanas montadas com o arquivo "Outros Diesel" ou com um token mal alinhado da gasolina Premium. Mistura de grades de diesel. | Diesel S10 e S500 juntos, preço de lista. Semanas sem vigência de S10/S500 saem. Três semanas só com S10 ficam registradas no changelog. |
| Finanças Petrobras | 1T26 vazio; 2T26 só com volume. | Volumes, receitas e RT&M de 1T26 e 2T26, do Relatório de Produção e Vendas e do ITR. |

O snapshot não inclui tabelas brutas de produção (`anp_fuel_price_station`, `anp_weekly_weighted_price`, `petrobras_fuel_price_record`, `fuel_price_source_files`). Essas tabelas alimentam as séries semanais agregadas.

## 2. Fontes de dados

Cada fonte abaixo tem instituição, conteúdo, forma da coleta, periodicidade e referência ABNT. A coleta operacional do Gas Flare é semanal. O Proj IV usa o estado congelado desses arquivos.

### 2.1 ABICOM — PPI (Índice de Paridade de Preços)

**Instituição:** Associação Brasileira dos Importadores de Combustíveis (ABICOM).

**Conteúdo:** diferencial diário entre o preço Petrobras (e o preço nos polos independentes) e a paridade internacional de gasolina e diesel, em R$/L e em %.

**Forma da coleta:** a ABICOM publica uma imagem por data na categoria PPI do sítio. A imagem reproduz o cartão enviado por WhatsApp. O pipeline baixa a imagem, aplica máscara por período de layout e extrai os números por OCR (OCR.space). O catálogo de datas e URLs fica em `ppi_reference_table`. Os valores extraídos ficam em `ppi_daily`.

**Periodicidade da publicação:** diária em dias úteis, com falhas ocasionais.

**Periodicidade da coleta:** semanal. O orquestrador percorre páginas novas da categoria PPI, baixa imagens ausentes e reprocessa filas de qualidade.

**Base de preço:** o percentual é o desvio sobre o preço Petrobras: (preço Petrobras − paridade) / preço Petrobras. Em 2026 a razão R$/% fica constante entre reajustes e confirma o divisor. Em 2022–2025 os percentuais são inteiros pequenos, e a razão não mostra o divisor. Em 2026, o preço Petrobras do PPI é o preço com desconto das tabelas da Petrobras, enquanto essa coluna existe: gasolina até 10 set. 2026; diesel de 1º jun. 2026 em diante.

**Validação:** para cada par (Petrobras e independentes, gasolina e diesel), a carga ignora linhas com |%| < 10, calcula o preço de referência como mediana de R$ / % × 100 nos dez dias úteis anteriores e compara o percentual com o esperado. Divergência acima de 1,5 ponto percentual vai para conferência manual (`man_insp`).

**Recorte no snapshot:** 5 jan. 2022 a 21 set. 2026 (1.151 datas).

**Referência:**

ASSOCIAÇÃO BRASILEIRA DOS IMPORTADORES DE COMBUSTÍVEIS. *PPI*. Rio de Janeiro: ABICOM, 2026. Disponível em: https://abicom.com.br/categoria/ppi/. Acesso em: 19 ago. 2026.

### 2.2 ANP — preços médios ponderados semanais ao produtor e ao importador

**Instituição:** Agência Nacional do Petróleo, Gás Natural e Biocombustíveis (ANP).

**Conteúdo:** preço médio ponderado semanal de produtores e importadores, sem ICMS, com CIDE, PIS/Pasep e Cofins quando incidem. O arquivo traz as colunas Norte, Nordeste, Centro-Oeste, Sul, Sudeste e Brasil. A base usa só a coluna Brasil.

**Produtos:** diesel é a média simples das linhas `Óleo Diesel S-10 (R$/litro)` e `Óleo Diesel S-500 (R$/litro)`. Gasolina é a linha `Gasolina A Comum (R$/litro)`. A linha `Óleo Diesel²` é o total do diesel automotivo (nota de rodapé da ANP) e fica fora, para não contar a mesma venda duas vezes. Biodiesel B-100, diesel marítimo, diesel não rodoviário e gasolina Premium também ficam fora.

**Forma da coleta:** download HTTP do arquivo `precos-medios-ponderados-semanais-2013.xls`, com o histórico completo. A carga usa o arquivo mais novo.

**Comportamento em 2026:** a variação semanal típica é três a quatro vezes maior que em 2022–2025, sobretudo no diesel S-10. O valor é o da coluna Brasil da ANP. Como a ANP pondera pelo volume, uma causa provável é a parcela importada de cada semana, com o preço Petrobras muito abaixo da paridade.

**Periodicidade da publicação:** semanal. A ANP pondera o preço pelo volume vendido e atualiza o arquivo cerca de 12 dias após o fim da semana.

**Periodicidade da coleta:** semanal, com janela recente de meses no pipeline de preços.

**Recorte no snapshot:** semanas de 3 jan. 2022 a 13 set. 2026 (245 semanas por produto).

**Referência:**

AGÊNCIA NACIONAL DO PETRÓLEO, GÁS NATURAL E BIOCOMBUSTÍVEIS. *Preços de produtores e importadores de derivados de petróleo e biodiesel*. Brasília: ANP, 2026. Disponível em: https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-de-produtores-e-importadores-de-derivados-de-petroleo-e-biodiesel. Acesso em: 27 set. 2026.

### 2.3 ANP — vendas nacionais mensais de combustíveis

**Instituição:** Agência Nacional do Petróleo, Gás Natural e Biocombustíveis (ANP).

**Conteúdo:** volume nacional mensal de gasolina C e óleo diesel, em m³. O valor nacional é a soma dos estados.

**Forma da coleta:** duas origens em sequência. Primeiro o `.xls` da página de dados estatísticos (`vendas-combustiveis-m3.xls`). Se esse arquivo falhar, o pipeline tenta o CSV de dados abertos (`vendas-combustiveis-m3-1990-<ano>.csv`). O parser localiza os blocos nacionais e desempilha o grade mês × ano.

**Periodicidade da publicação:** mensal, com defasagem típica de cerca de dois meses.

**Periodicidade da coleta:** semanal. A maior parte das rodadas só confirma o último mês já publicado.

**Recorte no snapshot:** jan. 2022 a jul. 2026 (110 linhas; 55 meses × 2 produtos).

**Referência:**

AGÊNCIA NACIONAL DO PETRÓLEO, GÁS NATURAL E BIOCOMBUSTÍVEIS. *Vendas de combustíveis (m³)*. Brasília: ANP, 2026. Disponível em: https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-estatisticos. Acesso em: 19 ago. 2026.

AGÊNCIA NACIONAL DO PETRÓLEO, GÁS NATURAL E BIOCOMBUSTÍVEIS. *Dados abertos*: vendas de derivados de petróleo e etanol. Brasília: ANP, 2026. Disponível em: https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/vdpb/vendas-derivados-petroleo-e-etanol/. Acesso em: 19 ago. 2026.

### 2.4 Petrobras — tabelas de preço às distribuidoras

**Instituição:** Petróleo Brasileiro S.A. (Petrobras).

**Conteúdo:** preço de venda de gasolina e diesel às distribuidoras, publicado em PDF por data de vigência. O pipeline extrai as linhas e monta médias semanais.

**Base de preço:** preço de lista, "sem tributos, à vista". A média usa todos os locais e modalidades de venda (EXA, LPA, LCT, LTM, ETD, ETM, LPD, LPC). A coluna "com descontos" (MP 1.358, MP 1.363 e MP 1.391) fica fora. Gasolina é a gasolina A, sem a Premium. Diesel é a média de S10 e S500; o arquivo "Outros Diesel" fica fora. Três semanas têm só S10 (19 dez. 2022, 20 jan. 2025 e 17 fev. 2025), porque a tabela S500 não tem vigência nelas.

**Diferença para o PPI:** em 2026 o PPI segue a coluna com desconto, e esta série segue o preço de lista. As duas séries medem preços diferentes.

**Forma da coleta:** consulta à API Liferay Headless Delivery em `precos.petrobras.com.br` (pastas Gasolina = `1296640` e Diesel = `1296637`). O coletor baixa o PDF mais novo de cada pasta. O parser lê o PDF e grava registros por produto e data de vigência. A série semanal é uma agregação posterior.

**Periodicidade da publicação:** irregular. A Petrobras publica quando altera o preço. O diesel pode ficar meses sem mudança.

**Periodicidade da coleta:** semanal. Sem PDF novo, a série semanal não avança.

**Recorte no snapshot:** gasolina de 10 jan. 2022 a 13 set. 2026 (64 semanas); diesel de 10 jan. 2022 a 20 set. 2026 (72 semanas).

**Referência:**

PETROBRAS. *Tabelas de preços de venda às distribuidoras*. Rio de Janeiro: Petrobras, 2026. Disponível em: https://precos.petrobras.com.br. Acesso em: 19 ago. 2026.

### 2.5 Petrobras — Relatório de Produção e Vendas e demonstrações financeiras

**Instituição:** Petróleo Brasileiro S.A. (Petrobras), Central de Resultados.

**Conteúdo:** duas famílias. (1) Volume trimestral doméstico de diesel e gasolina C, em mil barris/dia (`pbr_quarterly_sales`). (2) Volume, receita e margem do segmento RT&M (`pbr_quarterly_diesel_gasoline`), a partir do Relatório de Produção e Vendas e das Demonstrações Financeiras em R$ (ITR).

**Forma da coleta:** API mziq File Manager (`apicatalog.mziq.com`), empresa `25fdf098-34f5-4608-b7fa-17d60b2de47d`. O coletor lista os PDFs por ano e categoria, baixa o arquivo e extrai tabelas por texto. Categorias: `central_de_resultados_relatorio_de_producao_de_vendas` e `central_de_resultados_demonstracoes_financeiras_em_rs`.

**Periodicidade da publicação:** trimestral, cerca de um a dois meses após o fim do trimestre.

**Periodicidade da coleta:** semanal na operação. Na prática a tabela só muda após novo release.

**Recorte no snapshot:** vendas trimestrais de 2022T1 a 2026T2 (36 linhas). Finanças de 2006T1 a 2026T2 (82 trimestres).

**Subvenção em 2026:** a receita RT&M da nota 8 do ITR não desconta a subvenção ao diesel rodoviário. A nota 4 inclui essa subvenção na receita de vendas: R$ 672 milhões em 1T26 e R$ 9.737 milhões em 2T26. O 2T26 também tem R$ 816 milhões de subvenção à gasolina. O campo `extraction_note` registra esses valores.

**Referência:**

PETROBRAS. *Central de resultados*. Rio de Janeiro: Petrobras, 2026. Disponível em: https://www.investidorpetrobras.com.br/resultados-e-comunicados/central-de-resultados/. Acesso em: 19 ago. 2026.

### 2.6 ABCR — Índice de tráfego em pedágios

**Instituição:** Associação Brasileira de Concessionárias de Rodovias (ABCR), divulgação em Melhores Rodovias.

**Conteúdo:** índice mensal de fluxo em concessões, nas classes leve, pesado e total (Brasil). Leves acompanham demanda de gasolina. Pesados acompanham demanda de diesel de frete.

**Forma da coleta:** download HTTP de planilha `.xlsx` em caminho WordPress. O nome do arquivo traz o mês dos dados (`abcr_MMYY.xlsx`). A pasta traz o mês de publicação. O coletor tenta URLs recentes e usa a primeira planilha válida. A série nacional sai da aba Original (bloco Brasil: LEVES / PESADOS / TOTAL).

**Periodicidade da publicação:** mensal, cerca de duas a quatro semanas após o fim do mês.

**Periodicidade da coleta:** semanal. Sem planilha nova, os registros não mudam.

**Recorte no snapshot:** fev. 2022 a ago. 2026 (165 linhas; 55 meses × 3 classes).

**Referência:**

ASSOCIAÇÃO BRASILEIRA DE CONCESSIONÁRIAS DE RODOVIAS. *Índice ABCR*. São Paulo: ABCR, 2026. Disponível em: https://melhoresrodovias.org.br/. Acesso em: 19 ago. 2026.

### 2.7 IBGE — SIDRA (desemprego, varejo e indústria)

**Instituição:** Instituto Brasileiro de Geografia e Estatística (IBGE).

**Conteúdo:** três séries mensais nacionais via API SIDRA.

| Código SIDRA | Nome na base | Variável | Unidade |
|---|---|---|---|
| 6381 | Unemployment Rate (PNAD) | 4099 | percent |
| 8880 | Retail Trade Volume Index (PMC) | 7169 (c11046/56734) | index |
| 8888 | Industrial Production Index (PIM-PF) | 12606 (c544/129314) | index |

**Forma da coleta:** GET JSON na API `https://apisidra.ibge.gov.br/values`. Cada indicador sai em uma chamada. A coleta é incremental: o coletor pede períodos novos, com um mês de sobreposição para revisão tardia.

**Periodicidade da publicação:** mensal. PMC e PIM-PF saem com cerca de um mês e meio a dois meses de defasagem.

**Periodicidade da coleta:** semanal (três chamadas HTTP por rodada).

**Recorte no snapshot:** jan. 2022 a jul. 2026 (165 linhas; 55 meses × 3 indicadores).

**Referência:**

INSTITUTO BRASILEIRO DE GEOGRAFIA E ESTATÍSTICA. *SIDRA*: Sistema IBGE de Recuperação Automática. Rio de Janeiro: IBGE, 2026. Disponível em: https://sidra.ibge.gov.br/. Acesso em: 19 ago. 2026.

INSTITUTO BRASILEIRO DE GEOGRAFIA E ESTATÍSTICA. *Pesquisa Nacional por Amostra de Domicílios Contínua*: tabela 6381. Rio de Janeiro: IBGE, 2026. Disponível em: https://sidra.ibge.gov.br/tabela/6381. Acesso em: 19 ago. 2026.

INSTITUTO BRASILEIRO DE GEOGRAFIA E ESTATÍSTICA. *Pesquisa Mensal de Comércio*: tabela 8880. Rio de Janeiro: IBGE, 2026. Disponível em: https://sidra.ibge.gov.br/tabela/8880. Acesso em: 19 ago. 2026.

INSTITUTO BRASILEIRO DE GEOGRAFIA E ESTATÍSTICA. *Pesquisa Industrial Mensal – Produção Física*: tabela 8888. Rio de Janeiro: IBGE, 2026. Disponível em: https://sidra.ibge.gov.br/tabela/8888. Acesso em: 19 ago. 2026.

### 2.8 B3 — Cotações históricas (PETR4)

**Instituição:** B3 S.A. – Brasil, Bolsa, Balcão.

**Conteúdo:** barras diárias de PETR4 no mercado à vista: abertura, máxima, mínima, média, último, ofertas, número de negócios, quantidade e volume financeiro. A série histórica da B3 cobre títulos negociados desde 1986. Os preços saem na moeda e na forma da época, sem ajuste por inflação ou proventos.

**Forma da coleta:** arquivo texto de largura fixa no produto *Cotações históricas*. A B3 distribui o arquivo em `.zip`. Depois da extração, o conteúdo é `.txt` (família COTAHIST: diário `COTAHIST_Dddmmaaaa.TXT`, mensal ou anual). A interpretação usa o layout oficial (tipo de registro 01, posições fixas, dois últimos dígitos de preço como decimais). O snapshot guarda o papel PETR4 já parseado em `equity_daily`. Campos `vol_hist*` não vêm do arquivo COTAHIST; o processo de carga os calcula depois (volatilidade histórica).

**Periodicidade da publicação:** um pregão por dia útil. A B3 publica arquivos diários, mensais e anuais.

**Periodicidade da coleta:** sob demanda a partir do arquivo histórico. O snapshot do curso não atualiza sozinho.

**Recorte no snapshot:** 1º fev. 2022 a 18 set. 2026 (1.156 pregões). Só o ticker PETR4. A série começa um mês depois do PPI.

**Referência:**

B3 S.A. – BRASIL, BOLSA, BALCÃO. *Cotações históricas*. São Paulo: B3, 2026. Disponível em: https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/mercado-a-vista/cotacoes-historicas/. Acesso em: 19 ago. 2026.

B3 S.A. – BRASIL, BOLSA, BALCÃO. *Layout do arquivo de cotações históricas*. São Paulo: B3, 2026. Disponível em: https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf. Acesso em: 19 ago. 2026.

### 2.9 BCB / IBGE / FGV — inflação (IPCA, IPCA-15, IGP-M)

**Instituição:** IBGE (IPCA e IPCA-15) e FGV (IGP-M). A série no snapshot vem do SGS do Banco Central do Brasil (cópia oficial, sem chave).

**Conteúdo:** quatro séries mensais nacionais em `inflation_monthly`.

| `series` | `metric` | Código SGS | Conteúdo |
|---|---|---|---|
| `ipca` | `mom_pct` | 433 | Variação mensal do IPCA |
| `ipca15` | `mom_pct` | 7478 | Variação mensal do IPCA-15 |
| `igpm` | `mom_pct` | 189 | Variação mensal do IGP-M |
| `ipca` | `yoy_pct` | 13522 | IPCA acumulado em 12 meses (não é IPCA-15) |

O IPCA-15 é mensal, com janela de coleta deslocada. Junto com o IPCA, o calendário de divulgação dá duas leituras de inflação ao consumidor por mês. O IGP-M é o índice geral de preços da FGV.

**Forma da coleta:** GET JSON em `https://api.bcb.gov.br/dados/serie/bcdata.sgs.{código}/dados`. Sem autenticação.

**Periodicidade da publicação:** mensal. IPCA cerca do dia 12 do mês seguinte; IPCA-15 cerca do dia 25 do mês de referência; IGP-M no fim do mês de referência.

**Periodicidade da coleta (Gas Flare):** semanal, no passo de vendas. O Proj IV usa o estado congelado.

**Recorte no snapshot:** jan. 2022 a ago. 2026 (224 linhas; 56 meses × 4 séries).

**Referência:**

BANCO CENTRAL DO BRASIL. *Sistema Gerenciador de Séries Temporais (SGS)*. Brasília: BCB, 2026. Disponível em: https://www3.bcb.gov.br/sgspub/. Acesso em: 19 ago. 2026.

INSTITUTO BRASILEIRO DE GEOGRAFIA E ESTATÍSTICA. *IPCA e IPCA-15*. Rio de Janeiro: IBGE, 2026. Disponível em: https://www.ibge.gov.br/estatisticas/economicas/precos-e-custos/. Acesso em: 19 ago. 2026.

FUNDAÇÃO GETULIO VARGAS. *IGP-M*. Rio de Janeiro: FGV/IBRE, 2026.

## 3. Mapa fonte → tabela

| Fonte | Publicação | Coleta | Tabela no snapshot |
|---|---|---|---|
| ABICOM PPI | diária (dias úteis) | semanal (imagem + OCR) | `ppi_reference_table`, `ppi_daily` |
| ANP preços médios ponderados (produtor e importador) | semanal | semanal (XLS, coluna Brasil) | `anp_distributor_weekly_*`, `fuel_price_national_weekly` |
| ANP vendas | mensal (~2 meses de atraso) | semanal (XLS/CSV) | `anp_fuel_sales` |
| Petrobras preços às distribuidoras | irregular (PDF) | semanal (API Liferay) | `petrobras_distributor_weekly_*` |
| Petrobras Central de Resultados | trimestral | semanal (API mziq + PDF) | `pbr_quarterly_sales`, `pbr_quarterly_diesel_gasoline` |
| ABCR | mensal | semanal (XLSX) | `abcr_traffic_index` |
| IBGE SIDRA | mensal | semanal (JSON) | `ibge_indicators` |
| B3 Cotações históricas | diária (pregão) | arquivo texto COTAHIST | `equity_daily` |
| BCB SGS (IPCA / IPCA-15 / IGP-M) | mensal | semanal (JSON) | `inflation_monthly` |

## 4. Tabelas de armazenamento

Chave de cada tabela: arquivo, grão, unicidade, período e colunas. Tipos abaixo descrevem o conteúdo; no SQLite as datas estão em TEXT ISO (`YYYY-MM-DD` ou timestamp).

### 4.1 `ppi_reference_table`

Catálogo bruto das imagens PPI na ABICOM. Uma linha por data de imagem. Zona: origem.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `ppi_image_date` | DATE | não | Data da imagem no slug ABICOM. Única. |
| `ppi_image_url` | TEXT | sim | URL completa da imagem. |
| `ppi_image_file_name` | TEXT | sim | Nome do arquivo na URL. |

Unicidade: `ppi_image_date`. Linhas: 1.151. Período: 5 jan. 2022 a 21 set. 2026. Só entram datas com linha final em `ppi_daily`.

### 4.2 `ppi_daily`

Série canônica diária do PPI. Uma linha por data de relatório. Âncora temporal do projeto.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `report_date` | DATE | não | Data do relatório PPI. Única. |
| `pbr_gas_R` | REAL | sim | Diferencial Petrobras gasolina, R$/L. |
| `pbr_gas_pct` | REAL | sim | Diferencial Petrobras gasolina, %. |
| `pbr_die_R` | REAL | sim | Diferencial Petrobras diesel, R$/L. |
| `pbr_die_pct` | REAL | sim | Diferencial Petrobras diesel, %. |
| `ind_gas_R` | REAL | sim | Diferencial independentes (polos) gasolina, R$/L. Ausente no layout antigo. |
| `ind_gas_pct` | REAL | sim | Diferencial independentes gasolina, %. |
| `ind_die_R` | REAL | sim | Diferencial independentes diesel, R$/L. |
| `ind_die_pct` | REAL | sim | Diferencial independentes diesel, %. |
| `source_url` | TEXT | sim | URL da imagem usada na extração. |
| `man_insp` | INTEGER | sim | Estado da inspeção: `0` automático; `1` conferido na imagem; `-1` não final, aguarda revisão; `-2` só em 5 jan. 2022 e 11 jan. 2022, linhas com campos de independentes vazios e `source_url` de arquivos de 2023. |
| `raw_ocr` | TEXT | sim | Texto bruto do OCR. |
| `scraped_at` | DATETIME | sim | Instante da carga. |

Unicidade: `report_date`. Linhas: 1.151. Período: 5 jan. 2022 a 21 set. 2026. Distribuição de `man_insp`: 862 linhas `0`, 287 linhas `1`, 2 linhas `-2`.

Sinal: valor negativo indica preço Petrobras abaixo da paridade internacional.

### 4.3 `anp_distributor_weekly_gasoline`

Preço semanal ANP da gasolina A comum ao produtor e ao importador, coluna Brasil, em R$/L.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `week_start` | DATE | não | Segunda da semana. |
| `week_end` | DATE | não | Domingo da semana. |
| `avg_price_rs_l` | REAL | não | Preço médio da semana, R$/L. |
| `source_record_count` | INTEGER | não | Número de linhas-fonte na agregação. Gasolina: 1 em toda semana. |
| `computed_at` | DATETIME | não | Instante do recálculo. |

Unicidade: (`week_start`, `week_end`). Linhas: 245. Período: 3–9 jan. 2022 a 7–13 set. 2026.

### 4.4 `anp_distributor_weekly_diesel`

Mesmo desenho da tabela de gasolina, para diesel rodoviário: média simples das linhas Brasil de S-10 e S-500.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `week_start` | DATE | não | Segunda da semana. |
| `week_end` | DATE | não | Domingo da semana. |
| `avg_price_rs_l` | REAL | não | Preço médio da semana, R$/L. |
| `source_record_count` | INTEGER | não | Número de linhas-fonte na agregação. Diesel: 2 em toda semana. |
| `computed_at` | DATETIME | não | Instante do recálculo. |

Unicidade: (`week_start`, `week_end`). Linhas: 245. Período: 3–9 jan. 2022 a 7–13 set. 2026.

### 4.5 `fuel_price_national_weekly`

Série semanal nacional canônica. No snapshot o método é `anp_weekly_weighted_source`, com uma linha por produto. Os valores são os mesmos das duas tabelas ANP acima.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `week_start` | DATE | não | Segunda da semana. |
| `week_end` | DATE | não | Domingo da semana. |
| `product` | TEXT | não | `diesel` ou `gasoline`. |
| `avg_price` | REAL | sim | Preço médio de venda, R$/L. |
| `avg_purchase_price` | REAL | sim | Preço médio de compra, quando a fonte traz o campo. |
| `source_record_count` | INTEGER | não | Número de linhas-fonte. |
| `method` | TEXT | não | Método de agregação. Snapshot: `anp_weekly_weighted_source`. |
| `computed_at` | DATETIME | não | Instante do recálculo. |

Unicidade: (`week_start`, `week_end`, `product`, `method`). Linhas: 490. Período: 3–9 jan. 2022 a 7–13 set. 2026.

### 4.6 `petrobras_distributor_weekly_gasoline`

Média semanal do preço de lista Petrobras da gasolina A às distribuidoras, sem tributos, em R$/L. Semanas sem publicação nova não entram.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `week_start` | DATE | não | Segunda da semana. |
| `week_end` | DATE | não | Domingo da semana. |
| `avg_price_rs_l` | REAL | não | Preço médio da semana, R$/L. |
| `source_record_count` | INTEGER | não | Número de linhas extraídas dos PDFs. |
| `computed_at` | DATETIME | não | Instante do recálculo. |

Unicidade: (`week_start`, `week_end`). Linhas: 64. Período: 10–16 jan. 2022 a 7–13 set. 2026. A semana de 27 abr. 2026 não existe: não há vigência de gasolina A nessa data.

### 4.7 `petrobras_distributor_weekly_diesel`

Mesmo desenho da tabela de gasolina Petrobras, para diesel S10 e S500 juntos.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `week_start` | DATE | não | Segunda da semana. |
| `week_end` | DATE | não | Domingo da semana. |
| `avg_price_rs_l` | REAL | não | Preço médio da semana, R$/L. |
| `source_record_count` | INTEGER | não | Número de linhas extraídas dos PDFs. |
| `computed_at` | DATETIME | não | Instante do recálculo. |

Unicidade: (`week_start`, `week_end`). Linhas: 72. Período: 10–16 jan. 2022 a 14–20 set. 2026. Em 17 set. 2026 o preço de lista sobe R$ 1,00/L em todos os locais; a coluna com desconto não muda.

### 4.8 `anp_fuel_sales`

Volume nacional mensal ANP, em m³.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `product` | TEXT | não | `gasolina_c` ou `diesel`. |
| `month` | DATE | não | Primeiro dia do mês de referência. |
| `volume_m3` | REAL | sim | Volume nacional, m³. |
| `source_url` | TEXT | sim | URL do XLS ou CSV usado. |
| `scraped_at` | DATETIME | não | Instante da carga. |

Unicidade: (`product`, `month`). Linhas: 110. Período: jan. 2022 a jul. 2026.

### 4.9 `pbr_quarterly_sales`

Vendas domésticas trimestrais Petrobras, em mil barris por dia.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `product` | TEXT | não | `diesel` ou `gasolina_c`. |
| `year` | INTEGER | não | Ano civil. |
| `quarter` | INTEGER | não | Trimestre (1 a 4). |
| `sales_mbpd` | REAL | não | Vendas, mil barris/dia. |
| `source_file_url` | TEXT | não | URL do PDF no file manager mziq. |
| `source_file_date` | DATE | sim | Data do documento na Central de Resultados. |
| `scraped_at` | DATETIME | não | Instante da carga. |

Unicidade: (`product`, `year`, `quarter`). Linhas: 36. Período: 2022T1 a 2026T2.

### 4.10 `pbr_quarterly_diesel_gasoline`

Painel trimestral de volume, receita e margem RT&M. Uma linha por trimestre.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `quarter` | TEXT | não | Rótulo do trimestre (`1Q06` … `2Q26`). Único. |
| `year` | INTEGER | não | Ano civil. |
| `quarter_num` | INTEGER | não | Trimestre (1 a 4). |
| `diesel_mbpd` | REAL | sim | Volume de diesel, mil barris/dia. |
| `gasoline_mbpd` | REAL | sim | Volume de gasolina, mil barris/dia. |
| `diesel_revenue_rsmn` | REAL | sim | Receita de diesel, R$ milhões. |
| `gasoline_revenue_rsmn` | REAL | sim | Receita de gasolina, R$ milhões. |
| `total_revenue_rsmn` | REAL | sim | Soma das receitas de produto, R$ milhões. |
| `rtm_sales_revenue_rsmn` | REAL | sim | Receita de vendas do segmento RT&M, R$ milhões. |
| `rtm_gross_profit_rsmn` | REAL | sim | Lucro bruto RT&M, R$ milhões. |
| `rtm_gross_margin_pct` | REAL | sim | Margem bruta RT&M, %. |
| `source_prod_doc` | TEXT | sim | Nome do Relatório de Produção e Vendas. |
| `source_fin_doc` | TEXT | sim | Nome das Demonstrações Financeiras em R$ / ITR. |
| `extraction_note` | TEXT | sim | Nota de extração (Q4 derivado, ajuste etc.). |
| `updated_at` | TEXT | não | Instante da última extração. |

Unicidade: `quarter`. Linhas: 82. Período: 2006T1 a 2026T2. Antes de ~2019 vários campos RT&M e de linha de produto ficam vazios: a fonte ainda não publicava o detalhe. De 1T22 a 2T26 todos os campos estão preenchidos. A receita de 2026 inclui subvenção (seção 2.5).

### 4.11 `abcr_traffic_index`

Índice mensal de tráfego em pedágios, Brasil.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `month` | DATE | não | Primeiro dia do mês. |
| `vehicle_type` | TEXT | não | `light`, `heavy` ou `total`. |
| `traffic_index` | REAL | sim | Índice de fluxo (base da planilha ABCR). |
| `source_url` | TEXT | sim | URL do `.xlsx` usado. |
| `scraped_at` | DATETIME | não | Instante da carga. |

Unicidade: (`month`, `vehicle_type`). Linhas: 165. Período: fev. 2022 a ago. 2026.

### 4.12 `ibge_indicators`

Indicadores mensais IBGE via SIDRA.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `indicator_code` | TEXT | não | Código da tabela SIDRA (`6381`, `8880`, `8888`). |
| `indicator_name` | TEXT | sim | Nome curto gravado na carga. |
| `month` | DATE | não | Primeiro dia do mês de referência. |
| `value` | REAL | sim | Valor da série. |
| `unit` | TEXT | sim | `percent` ou `index`. |
| `source_url` | TEXT | sim | URL da consulta SIDRA. |
| `scraped_at` | DATETIME | não | Instante da carga. |

Unicidade: (`indicator_code`, `month`). Linhas: 165. Período: jan. 2022 a jul. 2026.

### 4.13 `equity_daily`

Barras diárias de PETR4 a partir das Cotações históricas da B3.

| Campo | Tipo | Nulo | Origem COTAHIST | Descrição |
|---|---|---|---|---|
| `id` | INTEGER | não | — | Identificador interno. |
| `tradedate` | DATE | não | DATA DO PREGÃO | Data do pregão. |
| `ticker` | TEXT | não | CODNEG | Código de negociação. Snapshot: `PETR4`. |
| `price_open` | REAL | sim | PREABE | Preço de abertura, R$/ação. |
| `price_max` | REAL | sim | PREMAX | Preço máximo do pregão. |
| `price_min` | REAL | sim | PREMIN | Preço mínimo do pregão. |
| `price_med` | REAL | sim | PREMED | Preço médio do pregão. |
| `price_last` | REAL | sim | PREULT | Último preço do pregão. |
| `offer_buy` | REAL | sim | PREOFC | Melhor oferta de compra. |
| `offer_sell` | REAL | sim | PREOFV | Melhor oferta de venda. |
| `total_transactions` | INTEGER | sim | TOTNEG | Número de negócios. |
| `total_quantity` | INTEGER | sim | QUATOT | Quantidade negociada (ações). |
| `total_cash` | REAL | sim | VOLTOT | Volume financeiro, R$. |
| `vol_hist` | REAL | sim | derivado | Volatilidade histórica de referência (janela longa). |
| `vol_hist_021` | REAL | sim | derivado | Volatilidade histórica em 21 pregões. |
| `vol_hist_126` | REAL | sim | derivado | Volatilidade histórica em 126 pregões. |
| `vol_hist_252` | REAL | sim | derivado | Volatilidade histórica em 252 pregões. |
| `source_db` | TEXT | sim | — | Base intermediária da carga. Snapshot: `dadodb_dev`. |
| `ingested_at` | DATETIME | sim | — | Instante da ingestão no snapshot. |

Unicidade: (`ticker`, `tradedate`). Linhas: 1.156. Período: 1º fev. 2022 a 18 set. 2026.

Os preços da B3 não têm ajuste por proventos. Para retorno de longo prazo, declare o tratamento (bruto vs. ajustado) no notebook.

### 4.14 `inflation_monthly`

Impressões mensais de inflação (IPCA, IPCA-15, IGP-M) via SGS do Banco Central.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `series` | TEXT | não | `ipca`, `ipca15` ou `igpm`. |
| `metric` | TEXT | não | `mom_pct` (variação mensal) ou `yoy_pct` (12 meses). |
| `series_name` | TEXT | sim | Nome curto da série. |
| `month` | DATE | não | Primeiro dia do mês de referência. |
| `value` | REAL | sim | Valor (percentual). |
| `unit` | TEXT | sim | Snapshot: `percent`. |
| `source` | TEXT | não | Snapshot: `bcb_sgs`. |
| `source_series` | INTEGER | sim | Código SGS (`433`, `7478`, `189`, `13522`). |
| `source_url` | TEXT | sim | URL da consulta SGS. |
| `scraped_at` | DATETIME | não | Instante da carga. |

Unicidade: (`series`, `metric`, `month`). Linhas: 224. Período: jan. 2022 a ago. 2026.

O código SGS `13522` é IPCA em 12 meses, não IPCA-15. O IPCA-15 mensal é `7478`.

### 4.15 `export_changelog`

Registro das correções feitas no pipeline de origem antes de cada export. Uma linha por correção e tabela.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | INTEGER | não | Identificador interno. |
| `changed_at` | TEXT | não | Instante da correção, ISO 8601 UTC. |
| `table_name` | TEXT | não | Tabela corrigida. |
| `scope` | TEXT | não | Linhas ou semanas afetadas. |
| `cause` | TEXT | não | Causa, filtro antigo e novo, e fonte usada. |
| `max_abs_change` | REAL | sim | Maior alteração absoluta de valor, quando se aplica. |

Linhas: 16 no export de 27 set. 2026.

## 5. Unidades e alinhamento

| Família | Unidade | Frequência nativa | Como alinhar ao PPI |
|---|---|---|---|
| PPI | R$/L e % | diária (dia útil) | índice-mestre |
| PETR4 | R$/ação | diária (pregão) | junção por data; pregões sem PPI ficam fora do índice PPI |
| Preços ANP / nacional | R$/L | semanal | repetir a semana nos dias úteis, ou agregar o PPI na semana |
| Preços Petrobras | R$/L | semanal irregular | o mesmo; furos são ausência de reajuste, não falha de coleta |
| Vendas ANP | m³ | mensal | forward-fill no mês |
| Vendas / finanças PBR | mbpd, R$ milhões, % | trimestral | forward-fill no trimestre |
| ABCR / IBGE | índice ou % | mensal | forward-fill no mês |
| Inflação (IPCA / IPCA-15 / IGP-M) | % | mensal | forward-fill no mês; `cpi_latest_mom` usa IPCA se o mês existir, senão IPCA-15 |

NaNs antes do início nativo de uma série são esperados. Não complete esses furos com valores inventados.

## 6. Referências

AGÊNCIA NACIONAL DO PETRÓLEO, GÁS NATURAL E BIOCOMBUSTÍVEIS. *Preços de produtores e importadores de derivados de petróleo e biodiesel*. Brasília: ANP, 2026. Disponível em: https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-de-produtores-e-importadores-de-derivados-de-petroleo-e-biodiesel. Acesso em: 27 set. 2026.

AGÊNCIA NACIONAL DO PETRÓLEO, GÁS NATURAL E BIOCOMBUSTÍVEIS. *Dados abertos*: vendas de derivados de petróleo e etanol. Brasília: ANP, 2026. Disponível em: https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/vdpb/vendas-derivados-petroleo-e-etanol/. Acesso em: 19 ago. 2026.

AGÊNCIA NACIONAL DO PETRÓLEO, GÁS NATURAL E BIOCOMBUSTÍVEIS. *Vendas de combustíveis (m³)*. Brasília: ANP, 2026. Disponível em: https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-estatisticos. Acesso em: 19 ago. 2026.

ASSOCIAÇÃO BRASILEIRA DE CONCESSIONÁRIAS DE RODOVIAS. *Índice ABCR*. São Paulo: ABCR, 2026. Disponível em: https://melhoresrodovias.org.br/. Acesso em: 19 ago. 2026.

ASSOCIAÇÃO BRASILEIRA DOS IMPORTADORES DE COMBUSTÍVEIS. *PPI*. Rio de Janeiro: ABICOM, 2026. Disponível em: https://abicom.com.br/categoria/ppi/. Acesso em: 19 ago. 2026.

BANCO CENTRAL DO BRASIL. *Sistema Gerenciador de Séries Temporais (SGS)*. Brasília: BCB, 2026. Disponível em: https://www3.bcb.gov.br/sgspub/. Acesso em: 19 ago. 2026.

B3 S.A. – BRASIL, BOLSA, BALCÃO. *Cotações históricas*. São Paulo: B3, 2026. Disponível em: https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/mercado-a-vista/cotacoes-historicas/. Acesso em: 19 ago. 2026.

B3 S.A. – BRASIL, BOLSA, BALCÃO. *Layout do arquivo de cotações históricas*. São Paulo: B3, 2026. Disponível em: https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf. Acesso em: 19 ago. 2026.

INSTITUTO BRASILEIRO DE GEOGRAFIA E ESTATÍSTICA. *Pesquisa Industrial Mensal – Produção Física*: tabela 8888. Rio de Janeiro: IBGE, 2026. Disponível em: https://sidra.ibge.gov.br/tabela/8888. Acesso em: 19 ago. 2026.

INSTITUTO BRASILEIRO DE GEOGRAFIA E ESTATÍSTICA. *Pesquisa Mensal de Comércio*: tabela 8880. Rio de Janeiro: IBGE, 2026. Disponível em: https://sidra.ibge.gov.br/tabela/8880. Acesso em: 19 ago. 2026.

INSTITUTO BRASILEIRO DE GEOGRAFIA E ESTATÍSTICA. *Pesquisa Nacional por Amostra de Domicílios Contínua*: tabela 6381. Rio de Janeiro: IBGE, 2026. Disponível em: https://sidra.ibge.gov.br/tabela/6381. Acesso em: 19 ago. 2026.

INSTITUTO BRASILEIRO DE GEOGRAFIA E ESTATÍSTICA. *SIDRA*: Sistema IBGE de Recuperação Automática. Rio de Janeiro: IBGE, 2026. Disponível em: https://sidra.ibge.gov.br/. Acesso em: 19 ago. 2026.

FUNDAÇÃO GETULIO VARGAS. *IGP-M*. Rio de Janeiro: FGV/IBRE, 2026.

PETROBRAS. *Central de resultados*. Rio de Janeiro: Petrobras, 2026. Disponível em: https://www.investidorpetrobras.com.br/resultados-e-comunicados/central-de-resultados/. Acesso em: 19 ago. 2026.

PETROBRAS. *Tabelas de preços de venda às distribuidoras*. Rio de Janeiro: Petrobras, 2026. Disponível em: https://precos.petrobras.com.br. Acesso em: 19 ago. 2026.
