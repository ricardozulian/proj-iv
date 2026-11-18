"""Reconstrói os experimentos da Etapa 4 somente a partir dos SQLite congelados."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone

from db_access import find_project_root
from etapa4_data import CURRENT_FREEZE, CURRENT_SHA256, SEP_EXPORT, sqlite_file
from paths import results_dir

MODULES = (
    "etapa4_audit", "etapa4_repro", "etapa4_finance_baseline", "etapa4_prod_contrib",
    "etapa4_price_transmission", "etapa4_demand", "etapa4_petr4_vol",
    "etapa4_inflation", "etapa4_company", "etapa4_independents", "etapa4_matrix",
)


def main() -> None:
    import warnings

    warnings.simplefilter("ignore")
    try:
        from etapa4_finance_baseline import _silence_statsmodels

        _silence_statsmodels()
    except Exception:
        pass
    root = find_project_root()
    before = {name: hashlib.sha256(sqlite_file(name, root).read_bytes()).hexdigest() for name in (CURRENT_FREEZE, SEP_EXPORT)}
    protected = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in [root / "src/etapa3_models.py", root / "results/etapa3_metrics.json", root / "results/etapa3_forecasts.json"]}
    started = datetime.now(timezone.utc).isoformat()
    for name in MODULES:
        print(f"REBUILD {name}", flush=True)
        importlib.import_module(name).main()
    assert all(hashlib.sha256(sqlite_file(name, root).read_bytes()).hexdigest() == digest for name, digest in before.items())
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in protected.items())
    report = {
        "protocol": "etapa4_review_20261016", "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "sqlite": CURRENT_FREEZE,
        "sha256_actual": before[CURRENT_FREEZE], "sha256_expected": CURRENT_SHA256,
        "sqlite_unchanged": True, "etapa3_unchanged": True, "modules_rebuilt": list(MODULES),
        "evaluation": "one-step observed target lags and updated persistence; realized contemporaneous regressors; fixed coefficients inside each block",
        "weekly_calendar": "Monday-Sunday; closed=left, label=left; price week_start/week_end",
        "selection": "exploratory on shared blocks; no independent confirmation; ex ante not executed",
        "python_version": platform.python_version(), "python_executable": sys.executable,
        "packages": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "statsmodels", "scikit-learn", "nbclient")},
    }
    (results_dir(root) / "etapa4_rebuild.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("REBUILD COMPLETE", flush=True)


if __name__ == "__main__":
    main()
