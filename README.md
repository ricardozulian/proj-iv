# Projeto Aplicado IV — paridade de combustíveis e a ação da Petrobras

Universidade Presbiteriana Mackenzie. Ciência de Dados EaD, 2026/02. Grupo 19.

Desenvolvimento de aplicação de séries temporais.

Documento oficial: [`notebooks/proj-iv_grupo19_etapa1.ipynb`](proj-iv_grupo19_etapa1.ipynb)
## Base

| Arquivo | Conteúdo |
|---------|----------|
| `data/gas_flare.sqlite` | Snapshot: PPI, preços, vendas, finanças, proxies, PETR4 e inflação (IPCA / IPCA-15 / IGP-M) |

Base coltedate a partir de diversas fontes com dados de inflação, atividade economica, preços/volumes de combustíveis e dados financeiros e de mercado da Petrobras.

Dicionário das tabelas: [`docs/metadados_base.md`](docs/metadados_base.md).

## Ambiente

1. Abra o diretório do projeto.
2. Crie o ambiente: `conda env create -f environment.yml`.
3. Ative o ambiente: `conda activate proj-iv`.
4. Registre o kernel:

```bash
python -m ipykernel install --user --name proj-iv --display-name "Python (proj_IV)"
```

5. Abra os notebooks com o kernel **Python (proj_IV)**.
6. Use o diretório de trabalho `proj_IV/` ou `proj_IV/notebooks/`.

## Pastas

```
proj_IV/
  data/           # SQLite congelado
  images/         # figuras do notebook de entrega
  notebooks/      # EDA e documento oficial
  src/            # acesso à base
  environment.yml # ambiente conda
```

## Leitura da base

```python
import sys
from pathlib import Path

cwd = Path.cwd().resolve()
root = cwd if (cwd / "src").is_dir() else cwd.parent
sys.path.insert(0, str(root / "src"))

from db_access import read_engine, resolve_database_url

ENGINE = read_engine(root)
print(resolve_database_url(root))  # sqlite:/.../data/gas_flare.sqlite
```

## Notebooks

| Arquivo | Conteúdo |
|---------|----------|
| `cd_projeto_aplicado_IV_doc` | Documento oficial da disciplina |
| `ppi_eda` | PPI (`ppi_daily`) |
| `price_eda` | Preços semanais ANP e Petrobras |
| `sales_eda` | Volumes ANP e Petrobras |
| `finance_eda` | Finanças trimestrais e margem RT&M |
| `proxies_eda` | Tráfego ABCR e indicadores IBGE |
| `equity_eda` | PETR4 (`equity_daily`) |
| `inflation_eda` | IPCA, IPCA-15 e IGP-M (`inflation_monthly`) |
| `compiled_eda` | `master_df` com âncora no PPI |
