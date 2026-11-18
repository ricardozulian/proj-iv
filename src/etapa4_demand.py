"""Exposure → demand and mobility (monthly, contemporaneous).

Diesel exposure with heavy traffic, diesel sales, industry.
Gasoline exposure with light traffic, gasoline sales, retail.
Lags 0–3 months. Seasonal persistence s=12 as extra baseline.
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import etapa3_models as e3
from db_access import find_project_root
from etapa4_data import CURRENT_FREEZE, CURRENT_SHA256, load_frames_at, sqlite_file
from etapa4_features import add_exposure_variants
from etapa4_prod_contrib import (
    _score,
    eval_named_groups,
    summarize,
    trailing_blocks,
)
from paths import results_dir

warnings.filterwarnings("ignore")

PAIRS = (
    ("abcr_heavy", "tráfego pesado", "die"),
    ("anp_die_m3", "vendas diesel ANP", "die"),
    ("pim", "indústria", "die"),
    ("abcr_light", "tráfego leve", "gas"),
    ("anp_gas_m3", "vendas gasolina ANP", "gas"),
    ("pmc", "varejo", "gas"),
)


def _groups(fuel: str) -> dict[str, list[str]]:
    exp = "prod_die_mn" if fuel == "die" else "prod_gas_mn"
    pos = "prod_die_pos_mn" if fuel == "die" else "prod_gas_pos_mn"
    neg = "prod_die_neg_mn" if fuel == "die" else "prod_gas_neg_mn"
    lags03 = [f"{exp}_l{k}" for k in range(0, 4)]
    return {
        "y_only": [],
        "y_seasonal": ["y_lag12"],
        "y_exp0": [f"{exp}_l0"],
        "y_exp_l03": lags03,
        "y_seasonal_exp": ["y_lag12", *lags03],
        "y_asym": [pos, neg],
    }


def seasonal_s12(y: pd.Series, blocks: list[pd.Index]) -> list[dict]:
    rows = []
    y = y.astype(float)
    for blk in blocks:
        hats = []
        for t in blk:
            loc = y.index.get_loc(t)
            hats.append(float(y.iloc[loc - 12]) if loc >= 12 else np.nan)
        yb = y.reindex(blk)
        hat = np.asarray(hats, dtype=float)
        for lab, n in (("1m", 1), ("3m", 3)):
            take = min(n, len(blk))
            rows.append(
                {
                    "block_start": str(pd.Timestamp(blk[0]).date()),
                    "block_end": str(pd.Timestamp(blk[-1]).date()),
                    "horizon": lab,
                    **_score(yb.iloc[:take], hat[:take]),
                }
            )
    return rows


def main() -> None:
    root = find_project_root()
    frames = add_exposure_variants(load_frames_at(sqlite_file(CURRENT_FREEZE, root), root))
    monthly = frames["monthly"].copy()
    monthly["y_lag12"] = np.nan  # filled per target
    blocks = trailing_blocks(monthly.index, e3.ACT_TRAIN_END, 4, 3, min_hist=24)
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "experiment": "monthly demand/mobility; fuel-matched exposure lags 0-3; seasonal s=12",
        "sqlite": CURRENT_FREEZE,
        "sha256": CURRENT_SHA256,
        "information": "contemporaneous / realized lags",
        "note": "Supports ODS 8 and 11. Compact groups (~55 monthly points).",
        "blocks": [f"{b[0].date()}..{b[-1].date()}" for b in blocks],
        "groups": {k: v for k, v in _groups("die").items()},
        "targets": {},
    }
    prefixes = [("1m", 1), ("3m", 3)]
    for col, lab, fuel in PAIRS:
        print(lab)
        y = monthly[col].astype(float)
        x = monthly.copy()
        x["y_lag12"] = y.shift(12)
        exp_cols = [c for c in monthly.columns if c.startswith("prod_")]
        x_full = x[["y_lag12", *exp_cols]]
        ev = eval_named_groups(y, x_full, _groups(fuel), blocks, prefixes, min_train=24)
        seas = seasonal_s12(y, blocks)
        packed = {
            "fuel": fuel,
            "groups": _groups(fuel),
            "summary": {
                g: {h: summarize(rows, ev["persistence"], h) for h in ("1m", "3m")}
                for g, rows in ev["groups"].items()
            },
            "seasonal_s12": {
                h: summarize(seas, ev["persistence"], h) for h in ("1m", "3m")
            },
            "rows": ev,
        }
        report["targets"][lab] = packed
        s = packed["summary"]["y_exp_l03"].get("3m") or {}
        s0 = packed["summary"]["y_only"].get("3m") or {}
        ss = packed["seasonal_s12"].get("3m") or {}
        print(
            f"  y_only={s0.get('median_RMSE')} exp_l03={s.get('median_RMSE')} "
            f"s12={ss.get('median_RMSE')} pers={s.get('persistence_median_RMSE')} "
            f"promote_exp={s.get('promote_ge_5pct')}"
        )
    out = results_dir(root) / "etapa4_demand.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
