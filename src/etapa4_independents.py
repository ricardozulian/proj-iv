"""Petrobras vs independent PPI (common-date sample, contemporaneous).

Relative gap = independent deviation minus Petrobras deviation (R$/L).
Independent exposure uses the same ANP volume as Petrobras exposure.
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

DAILY_GROUPS = {
    "y_only": [],
    "y_pbr": ["prod_mn"],
    "y_ind": ["prod_ind_mn"],
    "y_gap_gas": ["gap_gas_R"],
    "y_gap_die": ["gap_die_R"],
    "y_pbr_gap": ["prod_mn", "gap_gas_R", "gap_die_R"],
}


def _weekly_groups(fuel: str) -> dict[str, list[str]]:
    pbr = "prod_gas_mn_l0" if fuel == "gas" else "prod_die_mn_l0"
    ind = "prod_ind_gas_mn_l0" if fuel == "gas" else "prod_ind_die_mn_l0"
    gap = "gap_gas_R" if fuel == "gas" else "gap_die_R"
    gap_lags = [f"{gap}_l{k}" for k in range(0, 5)]
    return {
        "y_only": [],
        "y_pbr0": [pbr],
        "y_ind0": [ind],
        "y_gap0": [f"{gap}_l0"],
        "y_pbr_gap": [pbr, f"{gap}_l0"],
        "y_gap_l04": gap_lags,
    }


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
    daily = frames["daily"]
    price = frames["price_week"]
    common_g = daily[["pbr_gas_R", "ind_gas_R"]].notna().all(axis=1)
    common_d = daily[["pbr_die_R", "ind_die_R"]].notna().all(axis=1)
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "experiment": (
            "Petrobras vs independent PPI; gap = ind − pbr (R$/L); "
            "independent exposure = ind PPI × ANP volume"
        ),
        "sqlite": CURRENT_FREEZE,
        "sha256": CURRENT_SHA256,
        "information": "contemporaneous / realized lags; common-date sample",
        "note": (
            "Independent PPI starts 2022-11-01 (older card layout omits polos). "
            "Independent exposure uses the same ANP national volume as Petrobras "
            "exposure, so the difference is the PPI term. Gap is not a retail margin. "
            "ANP is producer/importer price."
        ),
        "common_dates": {
            "ind_from": "2022-11-01",
            "n_daily_gas": int(common_g.sum()),
            "n_daily_die": int(common_d.sum()),
            "gap_gas_mean": float(daily.loc[common_g, "gap_gas_R"].mean()),
            "gap_die_mean": float(daily.loc[common_d, "gap_die_R"].mean()),
        },
        "daily": {"groups": DAILY_GROUPS, "targets": {}},
        "weekly": {"targets": {}},
    }

    print("daily PETR4 dlog")
    d_blocks = trailing_blocks(daily.index, e3.MKT_TRAIN_END, 6, 21)
    report["daily"]["blocks"] = [f"{b[0].date()}..{b[-1].date()}" for b in d_blocks]
    x_d = daily[["prod_mn", "prod_ind_mn", "gap_gas_R", "gap_die_R"]]
    ev = eval_named_groups(
        daily["dlog_petr4"],
        x_d,
        DAILY_GROUPS,
        d_blocks,
        [("5d", 5), ("21d", 21)],
        min_train=40,
    )
    packed = _pack(ev, ("5d", "21d"))
    zc = zero_change(daily["dlog_petr4"], d_blocks, [("5d", 5), ("21d", 21)])
    packed["zero_change"] = {h: summarize(zc, ev["persistence"], h) for h in ("5d", "21d")}
    report["daily"]["targets"]["PETR4 dlog"] = packed
    s0 = packed["summary"]["y_only"].get("21d") or {}
    sg = packed["summary"]["y_pbr_gap"].get("21d") or {}
    print(
        f"  y_only={s0.get('median_RMSE')} pbr_gap={sg.get('median_RMSE')} "
        f"dummy={s0.get('persistence_median_RMSE')} promote_gap={sg.get('promote_ge_5pct')}"
    )

    print("weekly")
    w_blocks = trailing_blocks(price.index, e3.PRICE_TRAIN_END, 4, 8)
    report["weekly"]["blocks"] = [f"{b[0].date()}..{b[-1].date()}" for b in w_blocks]
    prefixes = [("4w", 4), ("8w", 8)]
    x_cols = [
        c
        for c in price.columns
        if c.startswith("prod_gas_mn")
        or c.startswith("prod_die_mn")
        or c.startswith("prod_ind_")
        or c.startswith("gap_")
    ]
    x_w = price[x_cols]
    for fuel, ycol, lab in [
        ("gas", "danp_gas", "ANP gasolina Δ"),
        ("die", "danp_die", "ANP diesel Δ"),
        ("gas", "anp_gas", "ANP gasolina"),
        ("die", "anp_die", "ANP diesel"),
    ]:
        print(" ", lab)
        groups = _weekly_groups(fuel)
        ev = eval_named_groups(
            price[ycol],
            x_w,
            groups,
            w_blocks,
            prefixes,
            min_train=40,
        )
        packed = _pack(ev, ("4w", "8w"))
        packed["fuel"] = fuel
        packed["groups"] = groups
        report["weekly"]["targets"][lab] = packed
        s0 = packed["summary"]["y_only"].get("8w") or {}
        sg = packed["summary"]["y_pbr_gap"].get("8w") or {}
        print(
            f"    y_only={s0.get('median_RMSE')} pbr_gap={sg.get('median_RMSE')} "
            f"dummy={s0.get('persistence_median_RMSE')} promote_gap={sg.get('promote_ge_5pct')}"
        )

    out = results_dir(root) / "etapa4_independents.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
