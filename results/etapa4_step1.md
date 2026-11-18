# Etapa 4 — passo 1 (16/10/2026)

Validação da revisão da base e reprodução da referência naive. Artefatos em `results/etapa4_*`. `results/etapa3_metrics.json` não foi alterado. Notebooks 1–3 não foram editados.

## Hashes

| Arquivo | SHA-256 | Papel |
|---|---|---|
| `data/gas_flare.sqlite` | `b314283c8e711becd802d5162be38b1c47052e9603d8bbf81345916fc2bf35ba` | freeze corrente |
| `data/gas_flare_export_20260927.sqlite` | `155f53607aae0e92e66a588288ce309a8bce05678b77b67a0b56603713db3a6d` | referência Etapa 3 |

Integrity check `ok` nos dois.

## RT&M

- Freeze corrente: 82/82 receita, lucro e margem (1Q06–2Q26).
- Export de setembro: 26/82.
- 4Q19 corrente: 72464 / 8010 / 11,0538%.
- 1Q22–2Q26 idêntico nos dois arquivos (0 mismatches).
- Volume diesel/gasolina: 28 observações cada. Receita de produto continua incompleta. Não tratar todos os campos da companhia como série de 82.

## Gasolina Petrobras (22 semanas)

Lista em `results/etapa4_gasoline_weeks.csv`. Cada semana ganhou 1 `source_record_count`. Maior alta de preço: R$ 0,009064661/L (semana 2023-06-12). Primeira semana 2022-01-10; última 2026-01-26. Todas estão no treino de preço (corte 19/07/2026). Nenhuma cai no teste 20/07–13/09/2026. O changelog (19 linhas) não explica essas 22 semanas. Proveniência ainda aberta. SARIMAX/Prophet de preço no freeze corrente usariam treino diferente; a naive não.

## Naive reproduzida

`src/etapa4_repro.py` + `results/etapa4_repro_naive.json`.

- Naive no export de setembro = `etapa3_metrics.json` (todas as linhas naive).
- Naive no freeze corrente = naive no export de setembro (incluindo Petrobras gasolina).

SARIMAX, Prophet e TimesFM continuam no JSON da Etapa 3 (Mac). Este host Windows não os refaz.

## Scripts

- `src/etapa4_data.py` — loader da Etapa 3 apontado a um SQLite nomeado.
- `src/etapa4_audit.py` — comparação das bases.
- `src/etapa4_repro.py` — naive nos dois SQLite.
- `src/etapa4_finance_baseline.py` — persistência / sazonal s=4 nos 82 trimestres.
