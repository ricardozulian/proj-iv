# Base Gas Flare — combustíveis no Brasil e a ação da Petrobras

A base reúne séries oficiais de diesel e gasolina, mais a cotação de PETR3/PETR4. O eixo temporal é o PPI da ABICOM: diferencial diário entre o preço Petrobras e a paridade internacional, em R$/L e em %, de 5 de janeiro de 2022 a 14 de agosto de 2026 (1.126 observações). As outras séries entram nesse calendário de dias úteis.

| Família | Frequência | Conteúdo | Início |
|---|---|---|---|
| PPI (ABICOM) | diária | diferencial Petrobras vs. paridade, gasolina e diesel | jan/2022 |
| Ação Petrobras | diária | PETR3/PETR4: abertura, máxima, mínima, fechamento, volume | alinhável ao PPI |
| Preços de combustível | semanal | ANP (distribuidor) e Petrobras (refinaria) | jan/2022 |
| Vendas | mensal / trimestral | volume ANP (m³) e Petrobras (mbpd) | jan/2022 |
| Finanças Petrobras | trimestral | volume, receita e margem RT&M | 2006 |
| Proxies de demanda | mensal | tráfego ABCR (leve/pesado); IBGE (desemprego, varejo, indústria) | jan/2022 |
| Inflação | mensal | IPCA, IPCA-15 (cobertura ~quinzenal de divulgação) e IGP-M | jan/2022 |

Fontes: ABICOM, ANP, Petrobras, B3, ABCR, IBGE, BCB/FGV. Snapshot congelado em SQLite (`data/gas_flare.sqlite`). Sem Postgres.

Dá para trabalhar previsão, nowcasting, transmissão de choques, defasagens, cointegração, VAR e MIDAS. Há duas séries diárias no mesmo calendário (PPI e ação) e o resto em frequência mista. Os dados conversam com os ODS 7 (energia), 8 (crescimento e emprego), 9 (indústria) e 12 (produção e consumo).

## Perguntas

Mercado. O PPI antecipa o retorno de PETR3/PETR4, ou o contrário? Um choque de paridade muda volume, receita ou margem no trimestre seguinte? Preço na refinaria e no distribuidor andam juntos, ou a defasagem persiste?

Energia (ODS 7). Quando o PPI se afasta da paridade, o preço ao consumidor sobe com que atraso? Preço mais alto corta o volume, ou a demanda segura no curto prazo?

Atividade e emprego (ODS 8). Choque de diesel antecipa menos tráfego pesado, menos varejo, mais desemprego? PPI e preços semanais dão nowcast de indústria, varejo e desemprego?

Indústria (ODS 9). Diesel e tráfego pesado antecipam a produção industrial? Tráfego leve e gasolina descrevem a mobilidade melhor que as vendas mensais da ANP?

Consumo (ODS 12). Paridade perto de zero versus desconto grande muda o mix gasolina/diesel e o uso da malha? Volume Petrobras e volume ANP se separam quando o preço doméstico fica abaixo do internacional?

A hipótese de trabalho é que choques de paridade e de preço passam primeiro pela ação e, depois, pela indústria, pelo varejo, pelo emprego e pelo tráfego.
