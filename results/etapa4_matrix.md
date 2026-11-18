# Etapa 4 — matriz por alvo

Gerada em 2026-10-18T21:22:24Z. Informação **contemporânea** (exposição realizada no horizonte).

## Base, modelo e exclusões

- Freeze: `gas_flare.sqlite` SHA-256 `b314283c8e711becd802d5162be38b1c47052e9603d8bbf81345916fc2bf35ba`.
- Referência Etapa 3: `gas_flare_export_20260927.sqlite` SHA-256 `155f53607aae0e92e66a588288ce309a8bce05678b77b67a0b56603713db3a6d`.
- Modelo: Ridge em um passo, intercepto, defasagens 1–2 do alvo realizadas, α ∈ {0,1; 1; 10; 100} no diário/semanal/mensal; α = 1 no trimestre casado.
- Dummy atualizada em cada data: y[t−1], com a mesma informação observada dos lags da Ridge. Os rótulos 8w, 3m e 21d indicam blocos, não previsões fixas de vários passos.
- Critério exploratório: RMSE mediano melhora ≥5%, vitória na maioria dos mesmos blocos e MAE mediano não superior contra o controle correspondente: `y_only`, `y_seasonal` ou o mesmo contexto sem exposição. A dummy aparece à parte. Empates de até 2% preservam a especificação mais simples.
- Comparação **dentro** de cada experimento (amostra idêntica). Independentes usam datas comuns a partir de 01/11/2022.
- Naive setembro = `etapa3_metrics.json`: True. Naive freeze = naive setembro: True.
- As 22 revisões da gasolina ficam no treino da Etapa 3, mas algumas alcançam a validação da Etapa 4. Proveniência aberta; igualdade da dummy não prova ausência de efeito nos modelos ajustados.
- Exclusões: viabilidade ex ante não executada; modelos históricos da Etapa 3 não reajustados; novo ensaio financeiro ARIMA/SARIMA/SES/Holt executado; PPI independente a partir de 01/11/2022; trimestre e volumes com exposição contemporânea descritivos; subvenções ITR nota 4 em 2026.

## Definições de exposição

- `prod_mn`: desvio PPI Petrobras × volume ANP (R$ milhões/dia; média na semana, soma no mês).
- `prod_pbr_mn`: mbpd Petrobras × 1000 × 159 L × desvio PPI, soma no trimestre.
- `prod_ind_mn`: PPI dos polos independentes × o mesmo volume ANP nacional.
- `gap`: desvio independente − desvio Petrobras (R$/L). Não é margem de varejo.
- `dqty_mn`: variação da quantidade de ações negociadas na B3, em milhões (`total_quantity`), não volume financeiro.

## Janelas de treino e blocos

- Diário e semanal: min_train = 40 observações comuns. Mensal: min_train = 24. Trimestre casado: min_pairs = 8, α = 1.
- Mercado diário: ['2026-02-19..2026-03-19', '2026-03-20..2026-04-20', '2026-04-22..2026-05-21', '2026-05-22..2026-06-22', '2026-06-23..2026-07-21', '2026-07-22..2026-08-19'].
- Preço semanal: ['2025-12-08..2026-01-26', '2026-02-02..2026-03-23', '2026-03-30..2026-05-18', '2026-05-25..2026-07-13'].
- Atividade/inflação mensal: ['2025-05-01..2025-07-01', '2025-08-01..2025-10-01', '2025-11-01..2026-01-01', '2026-02-01..2026-04-01'].
- Companhia (4 trimestres casados): ['2025-06-30', '2025-09-30', '2025-12-31', '2026-03-31'].
- Independentes: mesma grade, amostra comum a partir de 01/11/2022.

## Três efeitos separados

1. **Revisão da base.** Naive idêntica nos dois SQLite. RT&M passa de 26 para 82 trimestres; 1T22–2T26 inalterado. 4T19 = 72.464 / 8.010.
2. **História financeira.** Persistência usa o último trimestre; persistência sazonal usa t−4. Estes métodos não medem o benefício da história longa. ARIMA, SARIMA, SES e Holt comparam as janelas completa e de 40 trimestres no ensaio financeiro recalculado.
3. **Exposição PPI × volume.** Ver a tabela. Contribuição além da história do alvo só onde `ppi_x_vol` = sim.

## Comparações exploratórias (bloco de avaliação)

| Vetor | Alvo | Bloco | Controle | RMSE ctrl | PPI×vol | RMSE | vs y_only | Critério exploratório | Formulação |
|---|---|---|---|---:|---|---:|---:|---|---|
| mercado | PETR4 | 21d | `y_only` | 0.7354 | `y_prod` | 0.7306 | +0.7% | não | `y_only` |
| mercado | PETR4 dlog | 21d | `y_only` | 0.01654 | `y_dprod` | 0.01659 | -0.3% | não | `y_only` |
| mercado | RV 5 pregões | 21d | `y_dqty` | 0.004055 | `y_dprod_dqty` | 0.00402 | +3.2% | não | `y_dqty` |
| mercado | RV 21 pregões | 21d | `y_only` | 0.0008941 | `y_dprod` | 0.0008838 | +1.2% | não | `y_only` |
| preço | ANP gasolina | 8w | `y_only` | 0.387 | `y_prod` | 0.383 | +1.0% | não | `y_only` |
| preço | ANP diesel | 8w | `y_only` | 0.3375 | `y_pbr0` | 0.2893 | +14.3% | sim | `y_pbr0` |
| preço | Petrobras gasolina | 8w | `y_only` | 0.02754 | `y_dprod` | 0.04395 | -59.6% | não | `y_only` |
| preço | Petrobras diesel | 8w | `y_only` | 0.07015 | `y_dprod` | 0.103 | -46.8% | não | `y_only` |
| preço | ANP gasolina Δ | 8w | `y_only` | 0.4107 | `y_exp_l04` | 0.3826 | +6.8% | não | `y_only` |
| preço | ANP diesel Δ | 8w | `y_only` | 0.2768 | `y_exp0` | 0.2617 | +5.5% | não | `y_only` |
| atividade | tráfego pesado | 3m | `y_seasonal` | 2.554 | `y_seasonal_exp` | 2.848 | +62.1% | não | `y_seasonal` |
| atividade | tráfego leve | 3m | `y_seasonal` | 3.919 | `y_seasonal_exp` | 4.11 | +39.0% | não | `y_seasonal` |
| atividade | vendas diesel ANP | 3m | `y_seasonal` | 2.809e+05 | `y_seasonal_exp` | 2.818e+05 | +41.2% | descritivo | `y_seasonal` |
| atividade | vendas gasolina ANP | 3m | `y_only` | 2.443e+05 | `y_asym` | 1.453e+05 | +40.5% | descritivo | `y_asym` |
| atividade | indústria | 3m | `y_seasonal` | 2.414 | `y_seasonal_exp` | 3.58 | +39.1% | não | `y_seasonal` |
| atividade | varejo | 3m | `y_seasonal` | 1.907 | `y_seasonal_exp` | 1.562 | +63.5% | não | `y_seasonal` |
| atividade | desemprego | 3m | `y_only` | 0.2312 | `y_prod` | 0.2323 | -0.5% | não | `y_only` |
| inflação | IPCA mom | 3m | `y_only` | 0.2505 | `y_die_l03` | 0.25 | +0.2% | não | `y_anp_gas` |
| inflação | IPCA-15 mom | 3m | `y_seasonal` | 0.262 | `y_seasonal_exp` | 0.2503 | +1.8% | não | `y_seasonal` |
| inflação | IGP-M mom | 3m | `y_only` | 0.8064 | `y_die_l03` | 0.8501 | -5.4% | não | `y_only` |
| companhia | diesel mbpd | 4q | `y_only` | 41.84 | `y_die` | 34.37 | +17.8% | descritivo | `y_die` |
| companhia | gasolina mbpd | 4q | `y_only` | 11.37 | `y_prod` | 11.33 | +0.4% | descritivo | `y_only` |
| companhia | receita RT&M | 4q | `y_only` | 4671 | `y_gas` | 5262 | -12.6% | descritivo | `y_only` |
| companhia | lucro bruto RT&M | 4q | `dummy` | 5860 | `y_die` | 6006 | +18.5% | descritivo | `dummy` |
| companhia | margem RT&M | 4q | `dummy` | 5.084 | `y_die` | 5.54 | +12.3% | descritivo | `dummy` |
| companhia | margem derivada | 4q | `dummy` | 5.084 | `y_die` | 5.531 | +12.5% | descritivo | `dummy` |

## Leitura por alvo

- PETR4 (21d): PPI × volume não contribui além do controle `y_only` (RMSE 0,7354). Formulação: `y_only`.
- PETR4 dlog (21d): PPI × volume não contribui além do controle `y_only` (RMSE 0,0165). Formulação: `y_only`.
- RV 5 pregões (21d): PPI × volume não contribui além do controle `y_dqty` (RMSE 0,0041). Formulação: `y_dqty`.
  - No bloco 5d (petr4_vol), PPI×vol=não, gap=não, contexto=sim (melhor vol `y_dprod_dqty`).
- RV 21 pregões (21d): PPI × volume não contribui além do controle `y_only` (RMSE 0,0009). Formulação: `y_only`.
- ANP gasolina (8w): PPI × volume não contribui além do controle `y_only` (RMSE 0,3870). Formulação: `y_only`.
- ANP diesel (bloco 8w): `y_pbr0` atende ao critério exploratório contra `y_only`: RMSE 0,2893 vs 0,3375; vitórias 3/4. Não é evidência ex ante.
  - No bloco 4w (independents), PPI×vol=não, gap=não, contexto=não (melhor vol `y_ind0`).
- Petrobras gasolina (8w): PPI × volume não contribui além do controle `y_only` (RMSE 0,0275). Formulação: `y_only`.
- Petrobras diesel (8w): PPI × volume não contribui além do controle `y_only` (RMSE 0,0701). Formulação: `y_only`.
- ANP gasolina Δ (8w): PPI × volume não contribui além do controle `y_only` (RMSE 0,4107). Formulação: `y_only`.
- ANP diesel Δ (8w): PPI × volume não contribui além do controle `y_only` (RMSE 0,2768). Formulação: `y_only`.
- tráfego pesado (3m): PPI × volume não contribui além do controle `y_seasonal` (RMSE 2,554). Formulação: `y_seasonal`.
- tráfego leve (3m): PPI × volume não contribui além do controle `y_seasonal` (RMSE 3,919). Formulação: `y_seasonal`.
- vendas diesel ANP (3m): evidência descritiva (amostra trimestral). Controle `y_seasonal` RMSE 280.850,9. Melhor exposição `y_seasonal_exp` RMSE 281.777,8 vs `y_only` 479.459,7.
- vendas gasolina ANP (3m): evidência descritiva (amostra trimestral). Controle `y_only` RMSE 244.295,4. Melhor exposição `y_asym` RMSE 145.314,2 vs `y_only` 244.295,4.
- indústria (3m): PPI × volume não contribui além do controle `y_seasonal` (RMSE 2,414). Formulação: `y_seasonal`.
- varejo (3m): PPI × volume não contribui além do controle `y_seasonal` (RMSE 1,907). Formulação: `y_seasonal`.
  - No bloco 1m (demand), PPI×vol=sim, gap=não, contexto=não (melhor vol `y_seasonal_exp`). No bloco 1m (prod_contrib), PPI×vol=sim, gap=não, contexto=não (melhor vol `y_fuels`).
- desemprego (3m): PPI × volume não contribui além do controle `y_only` (RMSE 0,2312). Formulação: `y_only`.
- IPCA mom (3m): PPI × volume não contribui; o contexto `y_anp_gas` passa da história do alvo (RMSE 0,1995 vs 0,2505 de `y_only`).
  - No bloco 1m (inflation), PPI×vol=não, gap=não, contexto=não (melhor vol `y_seasonal_exp`).
- IPCA-15 mom (3m): PPI × volume não contribui além do controle `y_seasonal` (RMSE 0,2620). Formulação: `y_seasonal`.
- IGP-M mom (3m): PPI × volume não contribui além do controle `y_only` (RMSE 0,8064). Formulação: `y_only`.
- diesel mbpd (4q): evidência descritiva (amostra trimestral). Controle `y_only` RMSE 41,836. Melhor exposição `y_die` RMSE 34,368 vs `y_only` 41,836.
- gasolina mbpd (4q): evidência descritiva (amostra trimestral). Controle `y_only` RMSE 11,373. Melhor exposição `y_prod` RMSE 11,330 vs `y_only` 11,373.
- receita RT&M (4q): evidência descritiva (amostra trimestral). Controle `y_only` RMSE 4.671,5. Melhor exposição `y_gas` RMSE 5.262,4 vs `y_only` 4.671,5.
- lucro bruto RT&M (4q): evidência descritiva (amostra trimestral). Controle `dummy` RMSE 5.860,4. Melhor exposição `y_die` RMSE 6.005,9 vs `y_only` 7.368,9.
- margem RT&M (4q): evidência descritiva (amostra trimestral). Controle `dummy` RMSE 5,084. Melhor exposição `y_die` RMSE 5,540 vs `y_only` 6,319.
- margem derivada (4q): evidência descritiva (amostra trimestral). Controle `dummy` RMSE 5,084. Melhor exposição `y_die` RMSE 5,531 vs `y_only` 6,323.

## Onde PPI × volume contribui

- ANP diesel (8w): `y_pbr0`

## Onde o gap independentes−Petrobras contribui

- Nenhum alvo nesse bloco atende ao critério exploratório.

## Onde o contexto (não PPI × volume) contribui

- IPCA mom (3m): `y_anp_gas`

## Critério exploratório e limites da seleção

- PETR4 (21d): sem contribuição incremental demonstrada
- PETR4 dlog (21d): sem contribuição incremental demonstrada
- RV 5 pregões (21d): sem contribuição incremental demonstrada
- RV 21 pregões (21d): sem contribuição incremental demonstrada
- ANP gasolina (8w): sem contribuição incremental demonstrada
- ANP diesel (8w): critério exploratório atendido (PPI × volume)
- Petrobras gasolina (8w): sem contribuição incremental demonstrada
- Petrobras diesel (8w): sem contribuição incremental demonstrada
- ANP gasolina Δ (8w): sem contribuição incremental demonstrada
- ANP diesel Δ (8w): sem contribuição incremental demonstrada
- tráfego pesado (3m): sem contribuição incremental demonstrada
- tráfego leve (3m): sem contribuição incremental demonstrada
- vendas diesel ANP (3m): descritivo
- vendas gasolina ANP (3m): descritivo
- indústria (3m): sem contribuição incremental demonstrada
- varejo (3m): sem contribuição incremental demonstrada
- desemprego (3m): sem contribuição incremental demonstrada
- IPCA mom (3m): critério exploratório atendido (contexto)
- IPCA-15 mom (3m): sem contribuição incremental demonstrada
- IGP-M mom (3m): sem contribuição incremental demonstrada
- diesel mbpd (4q): descritivo
- gasolina mbpd (4q): descritivo
- receita RT&M (4q): descritivo
- lucro bruto RT&M (4q): descritivo
- margem RT&M (4q): descritivo
- margem derivada (4q): descritivo

