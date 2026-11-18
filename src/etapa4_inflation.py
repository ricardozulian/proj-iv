"""Exposure → inflation (monthly, contemporaneous).

IPCA, IPCA-15 and IGP-M month-on-month, each series on its own.
Fuel exposure lags 0–3 and monthly ANP price changes.
Does not overwrite etapa3_metrics.json.
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
from etapa4_prod_contrib import _score, eval_named_groups, summarize, trailing_blocks
from paths import results_dir

warnings.filterwarnings("ignore")

GROUPS = {
    "y_only": [],
    "y_seasonal": ["y_lag12"],
    "y_exp0": ["prod_mn_l0"],
    "y_gas_l03": [f"prod_gas_mn_l{k}" for k in range(0, 4)],
    "y_die_l03": [f"prod_die_mn_l{k}" for k in range(0, 4)],
    "y_anp_gas": ["danp_gas"],
    "y_anp_die": ["danp_die"],
    "y_seasonal_exp": ["y_lag12", *[f"prod_mn_l{k}" for k in range(0, 4)]],
}

TARGETS = (
    ("ipca", "IPCA mom"),
    ("ipca15", "IPCA-15 mom"),
    ("igpm", "IGP-M mom"),
)


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
    blocks = trailing_blocks(monthly.index, e3.ACT_TRAIN_END, 4, 3, min_hist=24)
    prefixes = [("1m", 1), ("3m", 3)]
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "experiment": "monthly IPCA / IPCA-15 / IGP-M; fuel exposure lags 0-3; ANP price changes",
        "sqlite": CURRENT_FREEZE,
        "sha256": CURRENT_SHA256,
        "information": "contemporaneous / realized lags",
        "note": "IPCA-15 stays a monthly series. Compact groups (~55 monthly points).",
        "blocks": [f"{b[0].date()}..{b[-1].date()}" for b in blocks],
        "groups": GROUPS,
        "targets": {},
    }
    x_cols = [
        *[f"prod_mn_l{k}" for k in range(0, 4)],
        *[f"prod_gas_mn_l{k}" for k in range(0, 4)],
        *[f"prod_die_mn_l{k}" for k in range(0, 4)],
        "danp_gas",
        "danp_die",
    ]
    for col, lab in TARGETS:
        print(lab)
        y = monthly[col].astype(float)
        x = monthly[x_cols].copy()
        x["y_lag12"] = y.shift(12)
        ev = eval_named_groups(y, x, GROUPS, blocks, prefixes, min_train=24)
        seas = seasonal_s12(y, blocks)
        packed = {
            "summary": {
                g: {h: summarize(rows, ev["persistence"], h) for h in ("1m", "3m")}
                for g, rows in ev["groups"].items()
            },
            "seasonal_s12": {h: summarize(seas, ev["persistence"], h) for h in ("1m", "3m")},
            "rows": ev,
        }
        report["targets"][lab] = packed
        s0 = packed["summary"]["y_only"].get("3m") or {}
        sd = packed["summary"]["y_die_l03"].get("3m") or {}
        ss = packed["seasonal_s12"].get("3m") or {}
        print(
            f"  y_only={s0.get('median_RMSE')} die_l03={sd.get('median_RMSE')} "
            f"s12={ss.get('median_RMSE')} dummy={s0.get('persistence_median_RMSE')} "
            f"promote_die={sd.get('promote_ge_5pct')}"
        )
    out = results_dir(root) / "etapa4_inflation.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
