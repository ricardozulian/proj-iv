"""Exposure → PETR4 log-return and realized volatility (daily, contemporaneous).

Targets: raw log-price change, 5-day RV, 21-day RV. B3 prices are unadjusted
for distributions. Does not overwrite etapa3_metrics.json.
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
    "y_dprod": ["dprod_mn"],
    "y_trail5": ["prod_mn_t5"],
    "y_trail21": ["prod_mn_t21"],
    "y_dqty": ["dqty_mn"],
    "y_dprod_dqty": ["dprod_mn", "dqty_mn"],
    "y_fuels": ["prod_gas_mn", "prod_die_mn"],
}

TARGETS = (
    ("dlog_petr4", "PETR4 dlog"),
    ("rv5", "RV 5 pregões"),
    ("rv21", "RV 21 pregões"),
)


def zero_change(y: pd.Series, blocks: list[pd.Index], prefixes: list[tuple[str, int]]) -> list[dict]:
    rows = []
    y = y.astype(float)
    for blk in blocks:
        hat = np.zeros(len(blk), dtype=float)
        yb = y.reindex(blk)
        for lab, n in prefixes:
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
    daily = frames["daily"]
    blocks = trailing_blocks(daily.index, e3.MKT_TRAIN_END, 6, 21)
    prefixes = [("5d", 5), ("21d", 21)]
    x_full = daily[["dprod_mn", "prod_mn_t5", "prod_mn_t21", "dqty_mn", "prod_gas_mn", "prod_die_mn"]]
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "experiment": "PETR4 log-return and realized vol 5/21; exposure change, trailing, volume change",
        "sqlite": CURRENT_FREEZE,
        "sha256": CURRENT_SHA256,
        "information": "contemporaneous / realized lags",
        "note": (
            "B3 prices are unadjusted for distributions. dlog is a raw-price change, "
            "not a total investment return. RV is the rolling standard deviation of "
            "daily log returns (unannualized)."
        ),
        "blocks": [f"{b[0].date()}..{b[-1].date()}" for b in blocks],
        "groups": GROUPS,
        "targets": {},
    }
    for col, lab in TARGETS:
        print(lab)
        y = daily[col].astype(float)
        ev = eval_named_groups(y, x_full, GROUPS, blocks, prefixes, min_train=40)
        packed = {
            "summary": {
                g: {h: summarize(rows, ev["persistence"], h) for h in ("5d", "21d")}
                for g, rows in ev["groups"].items()
            },
            "rows": ev,
        }
        if col == "dlog_petr4":
            zc = zero_change(y, blocks, prefixes)
            packed["zero_change"] = {
                h: summarize(zc, ev["persistence"], h) for h in ("5d", "21d")
            }
        report["targets"][lab] = packed
        s0 = packed["summary"]["y_only"].get("21d") or {}
        print(
            f"  y_only={s0.get('median_RMSE')} dummy={s0.get('persistence_median_RMSE')} "
            f"promote={s0.get('promote_ge_5pct')}"
        )
        for g, hs in packed["summary"].items():
            s = hs.get("21d") or {}
            if s:
                print(
                    f"  {g:14} RMSE={s['median_RMSE']:.5f} "
                    f"rel={s['rel_RMSE_vs_pers']:+.3f} promote={s['promote_ge_5pct']}"
                )
    out = results_dir(root) / "etapa4_petr4_vol.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
