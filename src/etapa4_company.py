"""Matched-history exposure and residual correction on RT&M (contemporaneous).

One exposure regressor per specification. Descriptive quarterly evidence:
no promotion rule. 2Q26 is the legacy point. 2026 subsidy quarters are
flagged. Does not overwrite etapa3_metrics.json.
"""

from __future__ import annotations

import json
import math
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
from etapa4_finance_baseline import forecast_with_meta, load_locked_baselines, load_rtm, origins as q_origins
from etapa4_prod_contrib import _score, persistence_hat, roll_ridge
from paths import results_dir

warnings.filterwarnings("ignore")

ALPHA = 1.0
MIN_TRAIN = 8
MIN_PAIRS = 8
SUBSIDY_QKEYS = {2026 * 4 + 1, 2026 * 4 + 2}  # 1Q26, 2Q26

MATCH_GROUPS = {
    "y_only": [],
    "y_prod": ["prod_pbr_mn"],
    "y_gas": ["prod_pbr_gas_mn"],
    "y_die": ["prod_pbr_die_mn"],
}

MATCH_TARGETS = (
    ("diesel_mbpd", "diesel mbpd"),
    ("gasoline_mbpd", "gasolina mbpd"),
    ("rtm_sales_revenue_rsmn", "receita RT&M"),
    ("rtm_gross_profit_rsmn", "lucro bruto RT&M"),
    ("rtm_gross_margin_pct", "margem RT&M"),
)

CORR_TARGETS = (
    ("rtm_sales_revenue_rsmn", "receita RT&M"),
    ("rtm_gross_profit_rsmn", "lucro bruto RT&M"),
    ("rtm_gross_margin_pct", "margem RT&M"),
)

CORR_X = (
    ("prod_pbr_mn", "prod"),
    ("prod_pbr_gas_mn", "gas"),
    ("prod_pbr_die_mn", "die"),
)


def qkey_of(ts: pd.Timestamp) -> int:
    t = pd.Timestamp(ts)
    q = (t.month - 1) // 3 + 1
    return int(t.year) * 4 + q


def quarter_blocks(index: pd.Index, end: pd.Timestamp, n: int) -> list[pd.Index]:
    before = index[index <= end]
    out = []
    for k in range(n, 0, -1):
        blk = before[-k : -k + 1] if k > 1 else before[-1:]
        if len(blk):
            out.append(blk)
    return out


def score_rows(rows: list[dict]) -> dict:
    y = [r["actual"] for r in rows]
    hat = [r["hat"] for r in rows]
    pers = [r["dummy"] for r in rows]
    s = _score(y, hat)
    sp = _score(y, pers)
    rel = (sp["RMSE"] - s["RMSE"]) / sp["RMSE"] if sp["RMSE"] else math.nan
    out = {
        "n": s["n"],
        "RMSE": s["RMSE"],
        "MAE": s["MAE"],
        "dummy_RMSE": sp["RMSE"],
        "dummy_MAE": sp["MAE"],
        "rel_RMSE_vs_dummy": rel,
    }
    if rows and all("baseline_hat" in r for r in rows):
        sb = _score(y, [r["baseline_hat"] for r in rows])
        out["baseline_RMSE"] = sb["RMSE"]
        out["baseline_MAE"] = sb["MAE"]
        out["rel_RMSE_vs_baseline"] = (
            (sb["RMSE"] - s["RMSE"]) / sb["RMSE"] if sb["RMSE"] else math.nan
        )
    return out


def matched_hats(y: pd.Series, x: pd.DataFrame, origins: list[pd.Timestamp]) -> list[dict]:
    y = y.astype(float)
    rows = []
    for t in origins:
        tr = y.index[y.index < t]
        if len(tr) < MIN_TRAIN:
            continue
        hat = roll_ridge(y, x, tr, pd.Index([t]), ALPHA, min_obs=MIN_TRAIN)
        dummy = float(persistence_hat(y.loc[tr], 1)[0])
        actual = float(y.loc[t]) if t in y.index else math.nan
        rows.append(
            {
                "date": str(pd.Timestamp(t).date()),
                "qkey": qkey_of(t),
                "actual": actual,
                "hat": float(hat[0]) if np.isfinite(hat[0]) else math.nan,
                "dummy": dummy,
                "subsidy_quarter": qkey_of(t) in SUBSIDY_QKEYS,
            }
        )
    return rows


def derived_margin(rev_rows: list[dict], gp_rows: list[dict]) -> list[dict]:
    by_q = {r["qkey"]: r for r in gp_rows}
    out = []
    for r in rev_rows:
        g = by_q.get(r["qkey"])
        if g is None:
            continue
        hat = math.nan
        dummy = math.nan
        if np.isfinite(r["hat"]) and r["hat"] > 0:
            hat = 100.0 * g["hat"] / r["hat"]
        else:
            hat = math.nan
        if np.isfinite(r["dummy"]) and r["dummy"] > 0:
            dummy = 100.0 * g["dummy"] / r["dummy"]
        rec = {
            "date": r["date"],
            "qkey": r["qkey"],
            "actual": math.nan,
            "hat": hat,
            "dummy": dummy,
            "rev_hat_nonpositive": (not np.isfinite(r["hat"])) or r["hat"] <= 0,
            "subsidy_quarter": r["subsidy_quarter"],
        }
        out.append(rec)
    return out


def attach_actual_margin(rows: list[dict], margin: pd.Series) -> list[dict]:
    m = margin.copy()
    m.index = [qkey_of(i) for i in m.index]
    for r in rows:
        if r["qkey"] in m.index:
            r["actual"] = float(m.loc[r["qkey"]])
    return rows


def ols_ab(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    X = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(beta[0]), float(beta[1])


def residual_correction(
    y: pd.Series,
    x: pd.Series,
    eval_keys: list[int],
    baseline_hats: dict[int, float],
    method: str,
    window: int | None,
) -> list[dict]:
    """Locked-baseline residual ~ intercept + one exposure. Fit on earlier pairs only."""
    rows = []
    y = y.astype(float)
    x = x.astype(float)
    for t in eval_keys:
        if t not in y.index or not np.isfinite(y.loc[t]):
            continue
        baseline_hat = baseline_hats.get(t, math.nan)
        dummy = float(y.loc[t - 1]) if (t - 1) in y.index else math.nan
        pairs_s, pairs_r, pairs_x = [], [], []
        for s in y.index:
            if s >= t:
                continue
            if s not in baseline_hats or not np.isfinite(baseline_hats[s]):
                continue
            if s not in x.index or not np.isfinite(x.loc[s]):
                continue
            if not np.isfinite(y.loc[s]):
                continue
            pairs_s.append(int(s))
            pairs_r.append(float(y.loc[s] - baseline_hats[s]))
            pairs_x.append(float(x.loc[s]))
        rec = {
            "qkey": t,
            "actual": float(y.loc[t]),
            "dummy": dummy,
            "baseline_hat": float(baseline_hat) if np.isfinite(baseline_hat) else math.nan,
            "hat": math.nan,
            "n_pairs": len(pairs_s),
            "alpha": math.nan,
            "beta": math.nan,
            "status": "insufficient_history",
            "method": method,
            "window": window,
            "subsidy_quarter": t in SUBSIDY_QKEYS,
        }
        if (
            len(pairs_s) < MIN_PAIRS
            or t not in x.index
            or not np.isfinite(x.loc[t])
            or not np.isfinite(baseline_hat)
        ):
            rows.append(rec)
            continue
        a, b = ols_ab(np.asarray(pairs_x, float), np.asarray(pairs_r, float))
        rec["alpha"] = a
        rec["beta"] = b
        rec["status"] = "fitted"
        rec["hat"] = float(baseline_hat + a + b * float(x.loc[t]))
        rows.append(rec)
    return rows


def _fitted(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("status") == "fitted"]


def pack_corr(rows: list[dict]) -> dict:
    mid = _fitted([r for r in rows if r["qkey"] <= 2026 * 4 + 1])
    pre2026 = _fitted([r for r in rows if r["qkey"] < 2026 * 4 + 1])
    legacy = _fitted([r for r in rows if r["qkey"] == 2026 * 4 + 2])
    return {
        "eval_1Q24_1Q26": score_rows(mid) if mid else {"n": 0, "n_fitted": 0},
        "eval_1Q24_4Q25": score_rows(pre2026) if pre2026 else {"n": 0, "n_fitted": 0},
        "legacy_2Q26": score_rows(legacy) if legacy else {"n": 0, "n_fitted": 0},
        "n_fitted": len(_fitted(rows)),
        "n_insufficient": sum(1 for r in rows if r.get("status") == "insufficient_history"),
        "points": rows,
    }


def baseline_forecasts(series: pd.Series, method: str, window: int | None, keys: list[int]) -> dict[int, float]:
    hats = {}
    for origin in keys:
        if origin not in series.index or not np.isfinite(series.loc[origin]):
            continue
        hat, _meta = forecast_with_meta(series, origin, method, window)
        hats[int(origin)] = float(hat)
    return hats


def main() -> None:
    root = find_project_root()
    frames = add_exposure_variants(load_frames_at(sqlite_file(CURRENT_FREEZE, root), root))
    fin = frames["fin"].copy()
    fin["qkey"] = fin["year"] * 4 + fin["quarter_num"]
    origins = [b[0] for b in quarter_blocks(fin.index, e3.COMP_TRAIN_END, 4)]
    origins_no26 = [t for t in origins if qkey_of(t) not in SUBSIDY_QKEYS]
    xfin = fin[["prod_pbr_mn", "prod_pbr_gas_mn", "prod_pbr_die_mn"]]

    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "experiment": "matched-history Ridge (one exposure) and locked-baseline residual correction",
        "sqlite": CURRENT_FREEZE,
        "sha256": CURRENT_SHA256,
        "information": "contemporaneous / realized exposure",
        "note": (
            "Descriptive. No promotion rule. 2Q26 is the legacy point. "
            "1Q26 sales include ITR note-4 diesel subsidy R$ 672 million; "
            "2Q26 includes diesel R$ 9.737 billion and a gasoline subsidy. "
            "Do not attribute residual differences to subsidies alone. "
            "Derived margin is 100 × GP hat / revenue hat; missing when revenue hat <= 0. "
            "Residual correction uses each target's locked financial-history baseline."
        ),
        "alpha_fixed": ALPHA,
        "matched_history": {
            "blocks": [str(pd.Timestamp(t).date()) for t in origins],
            "blocks_no_2026": [str(pd.Timestamp(t).date()) for t in origins_no26],
            "groups": MATCH_GROUPS,
            "targets": {},
            "derived_margin": {},
        },
        "residual_correction": {
            "min_pairs": MIN_PAIRS,
            "eval": "1Q24-1Q26",
            "legacy": "2Q26",
            "note": (
                "Residuals are actual minus the locked baseline forecast at each origin. "
                "Correction is OLS on earlier eligible pairs only. "
                "Fewer than eight pairs records insufficient_history and is not a fitted correction. "
                "Persistence remains a named dummy column; it is the control only when it is the locked baseline."
            ),
            "targets": {},
        },
    }

    print("matched history")
    hats_store = {}
    for col, lab in MATCH_TARGETS:
        print(" ", lab)
        y = fin[col]
        groups_out = {}
        for gname, cols in MATCH_GROUPS.items():
            x = xfin[cols] if cols else pd.DataFrame(index=y.index)
            rows = matched_hats(y, x, origins)
            rows_no = [r for r in rows if not r["subsidy_quarter"]]
            groups_out[gname] = {
                "all_4q": score_rows(rows),
                "no_2026": score_rows(rows_no) if rows_no else {},
                "points": rows,
            }
            hats_store[(lab, gname)] = rows
            s = groups_out[gname]["all_4q"]
            print(f"    {gname:8} RMSE={s['RMSE']:.4f} dummy={s['dummy_RMSE']:.4f} n={s['n']}")
        report["matched_history"]["targets"][lab] = groups_out

    print(" derived margin")
    margin = fin["rtm_gross_margin_pct"]
    for gname in MATCH_GROUPS:
        rev = hats_store[("receita RT&M", gname)]
        gp = hats_store[("lucro bruto RT&M", gname)]
        rows = attach_actual_margin(derived_margin(rev, gp), margin)
        n_fail = sum(1 for r in rows if r["rev_hat_nonpositive"])
        rows_no = [r for r in rows if not r["subsidy_quarter"]]
        report["matched_history"]["derived_margin"][gname] = {
            "all_4q": score_rows(rows),
            "no_2026": score_rows(rows_no) if rows_no else {},
            "rev_hat_nonpositive_n": n_fail,
            "points": rows,
        }
        s = report["matched_history"]["derived_margin"][gname]["all_4q"]
        print(f"    {gname:8} RMSE={s['RMSE']:.4f} dummy={s['dummy_RMSE']:.4f} fail={n_fail}")

    print("residual correction")
    rtm = load_rtm(root)
    locked = load_locked_baselines(root)
    exp = fin.set_index("qkey")[["prod_pbr_mn", "prod_pbr_gas_mn", "prod_pbr_die_mn"]]
    hist_keys = q_origins(2022, 1, 2026, 2)
    eval_keys = list(range(2024 * 4 + 1, 2026 * 4 + 2 + 1))  # 1Q24..2Q26
    for col, lab in CORR_TARGETS:
        print(" ", lab)
        y = rtm[col]
        base = locked[lab]
        method, window = base["method"], base["window"]
        hats = baseline_forecasts(y, method, window, hist_keys)
        uncorr_rows = []
        for t in eval_keys:
            if t not in y.index or t not in hats:
                continue
            uncorr_rows.append(
                {
                    "qkey": t,
                    "actual": float(y.loc[t]),
                    "dummy": float(y.loc[t - 1]) if (t - 1) in y.index else math.nan,
                    "baseline_hat": hats[t],
                    "hat": hats[t],
                    "n_pairs": 0,
                    "alpha": math.nan,
                    "beta": math.nan,
                    "status": "fitted",
                    "method": method,
                    "window": window,
                    "subsidy_quarter": t in SUBSIDY_QKEYS,
                }
            )
        block = {
            "baseline": {"method": method, "window": window},
            "uncorrected": pack_corr(uncorr_rows),
            "corrected": {},
        }
        for xcol, xlab in CORR_X:
            rows = residual_correction(y, exp[xcol], eval_keys, hats, method, window)
            packed = pack_corr(rows)
            packed["baseline"] = {"method": method, "window": window}
            block["corrected"][xlab] = packed
            s = packed["eval_1Q24_1Q26"]
            print(
                f"    {xlab:8} RMSE={s.get('RMSE')} baseline={s.get('baseline_RMSE')} "
                f"method={method} window={window} n={s.get('n')} "
                f"fitted={packed['n_fitted']} insufficient={packed['n_insufficient']}"
            )
        report["residual_correction"]["targets"][lab] = block

    out = results_dir(root) / "etapa4_company.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
