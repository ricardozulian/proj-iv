"""Exposure → price transmission (weekly, contemporaneous).

Targets are ANP price *changes*. Sequence: fuel exposure and Petrobras
list changes → ANP. Distributed lags 0–8 weeks. Does not overwrite
etapa3_metrics.json.
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


def _groups(fuel: str) -> dict[str, list[str]]:
    exp = "prod_gas_mn" if fuel == "gas" else "prod_die_mn"
    lst = "dpbr_gas" if fuel == "gas" else "dpbr_die"
    pos = "prod_gas_pos_mn" if fuel == "gas" else "prod_die_pos_mn"
    neg = "prod_gas_neg_mn" if fuel == "gas" else "prod_die_neg_mn"
    lags04 = [f"{exp}_l{k}" for k in range(0, 5)]
    lags08 = [f"{exp}_l{k}" for k in range(0, 9)]
    return {
        "y_only": [],
        "y_list": [lst],
        "y_exp0": [f"{exp}_l0"],
        "y_exp_l04": lags04,
        "y_exp_l08": lags08,
        "y_list_exp": [lst, *lags04],
        "y_asym": [pos, neg],
    }


def zero_change(y: pd.Series, blocks: list[pd.Index], prefixes: list[tuple[str, int]]) -> list[dict]:
    """Level random walk: forecast Δ = 0."""
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


def _pack(ev: dict, horizons: tuple[str, ...]) -> dict:
    return {
        "summary": {
            g: {h: summarize(rows, ev["persistence"], h) for h in horizons}
            for g, rows in ev["groups"].items()
        },
        "rows": ev,
    }


def main() -> None:
    root = find_project_root()
    frames = add_exposure_variants(load_frames_at(sqlite_file(CURRENT_FREEZE, root), root))
    price = frames["price_week"]
    blocks = trailing_blocks(price.index, e3.PRICE_TRAIN_END, 4, 8)
    prefixes = [("4w", 4), ("8w", 8)]
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "experiment": "weekly ANP price changes; exposure lags 0-8; Petrobras list changes",
        "sqlite": CURRENT_FREEZE,
        "sha256": CURRENT_SHA256,
        "information": "contemporaneous / realized lags",
        "note": (
            "ANP is producer/importer price. ANP minus Petrobras list mixes "
            "price bases and is not a retail margin. 22 gasoline list weeks "
            "revised inside Etapa 3 training; some overlap Etapa 4 validation (last 2026-01-26). Provenance remains open."
        ),
        "blocks": [f"{b[0].date()}..{b[-1].date()}" for b in blocks],
        "groups": {k: v for k, v in _groups("gas").items()},
        "targets": {},
    }
    x_cols = [c for c in price.columns if c.startswith("prod_") or c.startswith("dpbr_")]
    x_full = price[x_cols]
    for fuel, ycol, lab in [
        ("gas", "danp_gas", "ANP gasolina Δ"),
        ("die", "danp_die", "ANP diesel Δ"),
    ]:
        print(lab)
        groups = _groups(fuel)
        ev = eval_named_groups(
            price[ycol],
            x_full,
            groups,
            blocks,
            prefixes,
            min_train=40,
        )
        zc = zero_change(price[ycol], blocks, prefixes)
        packed = _pack(ev, ("4w", "8w"))
        packed["fuel"] = fuel
        packed["groups"] = groups
        packed["zero_change"] = {
            h: summarize(zc, ev["persistence"], h) for h in ("4w", "8w")
        }
        report["targets"][lab] = packed
        s0 = packed["summary"]["y_only"].get("8w") or {}
        z = packed["zero_change"].get("8w") or {}
        print(
            f"  y_only={s0.get('median_RMSE')} dummy={s0.get('persistence_median_RMSE')} "
            f"zeroΔ={z.get('median_RMSE')}"
        )
        for g, hs in packed["summary"].items():
            s = hs.get("8w") or {}
            if s:
                print(
                    f"  {g:12} RMSE={s['median_RMSE']:.4f} "
                    f"pers={s['persistence_median_RMSE']:.4f} "
                    f"rel={s['rel_RMSE_vs_pers']:+.3f} promote={s['promote_ge_5pct']}"
                )
    out = results_dir(root) / "etapa4_price_transmission.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
