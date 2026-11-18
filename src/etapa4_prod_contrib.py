"""Contemporaneous PPI × volume contribution (Ridge), Etapa 4.

Windows-safe. Does not overwrite etapa3_metrics.json.
Writes results/etapa4_prod_contrib.json.
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
from paths import results_dir

warnings.filterwarnings("ignore")

ALPHAS = (0.1, 1.0, 10.0, 100.0)
Y_LAGS = (1, 2)

GROUPS = {
    "y_only": [],
    "y_prod": ["prod_mn"],
    "y_fuels": ["prod_gas_mn", "prod_die_mn"],
    "y_dprod": ["dprod_mn"],
}


def _score(y, yhat) -> dict:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.isfinite(y) & np.isfinite(yhat)
    y, yhat = y[mask], yhat[mask]
    if y.size == 0:
        return {"MAE": math.nan, "RMSE": math.nan, "n": 0}
    err = y - yhat
    return {
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err * err))),
        "n": int(y.size),
    }


def _lag_cols(y: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(index=y.index)
    for k in Y_LAGS:
        out[f"y_lag{k}"] = y.shift(k)
    return out


def persistence_hat(train: pd.Series, n: int) -> np.ndarray:
    last = float(train.dropna().iloc[-1])
    return np.full(n, last)


def one_step_persistence(y: pd.Series, dates: pd.Index) -> np.ndarray:
    """Use the previous observed target at each evaluation date, like Ridge."""
    return y.shift(1).reindex(dates).to_numpy(float)


def _standardize(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu = np.mean(X, axis=0)
    sd = np.std(X, axis=0, ddof=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    return (X - mu) / sd, mu, sd


def fit_ridge(X: np.ndarray, y: np.ndarray, alpha: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    Xs, mu, sd = _standardize(X)
    y_mean = float(np.mean(y))
    yc = y - y_mean
    nfeat = Xs.shape[1]
    xtx = Xs.T @ Xs + alpha * np.eye(nfeat)
    xty = Xs.T @ yc
    beta = np.linalg.solve(xtx, xty)
    return beta, mu, sd, y_mean


def design(y: pd.Series, x: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    lags = _lag_cols(y)
    mat = lags.join(x, how="left")
    pack = mat.join(y.rename("y"), how="left").dropna()
    return pack.drop(columns=["y"]), pack["y"]


def roll_ridge(
    y_all: pd.Series,
    x_all: pd.DataFrame,
    train_idx,
    test_idx,
    alpha: float,
    min_obs: int = 20,
) -> np.ndarray:
    X, y = design(y_all, x_all)
    eligible = X.index.intersection(train_idx)
    X, y = X.loc[eligible], y.loc[eligible]
    if len(y) < min_obs:
        return np.full(len(test_idx), np.nan)
    beta, mu, sd, y_mean = fit_ridge(X.to_numpy(float), y.to_numpy(float), alpha)
    hats = []
    for t in test_idx:
        feats = {}
        loc = y_all.index.get_loc(t)
        for k in Y_LAGS:
            feats[f"y_lag{k}"] = float(y_all.iloc[loc - k]) if loc >= k else np.nan
        for col in x_all.columns:
            val = x_all.loc[t, col] if t in x_all.index else np.nan
            feats[col] = val
        row = np.array([feats[c] for c in X.columns], dtype=float)
        if not np.isfinite(row).all():
            hats.append(np.nan)
            continue
        xs = (row - mu) / sd
        hats.append(float(xs @ beta) + y_mean)
    return np.asarray(hats, dtype=float)


def trailing_blocks(
    index: pd.Index,
    end: pd.Timestamp,
    n_blocks: int,
    block: int,
    min_hist: int = 40,
) -> list[pd.Index]:
    idx = index[index <= end]
    out = []
    cursor = len(idx)
    for _ in range(n_blocks):
        start = cursor - block
        if start < min_hist:
            break
        out.append(idx[start:cursor])
        cursor = start
    return list(reversed(out))


def pick_alpha(
    y: pd.Series,
    x: pd.DataFrame,
    train_idx: pd.Index,
    block: int,
    min_train: int = 40,
) -> float:
    inner = trailing_blocks(train_idx, train_idx[-1], 3, block, min_hist=min_train)
    best_a, best = ALPHAS[1], math.inf
    for alpha in ALPHAS:
        rmses = []
        for blk in inner:
            tr = train_idx[train_idx < blk[0]]
            if len(tr) < min_train:
                continue
            hat = roll_ridge(y, x, tr, blk, alpha, min_obs=min_train)
            rmses.append(_score(y.reindex(blk), hat)["RMSE"])
        med = float(np.nanmedian(rmses)) if rmses else math.inf
        if med < best:
            best, best_a = med, alpha
    return best_a


def eval_named_groups(
    y: pd.Series,
    x_full: pd.DataFrame,
    groups: dict[str, list[str]],
    blocks: list[pd.Index],
    prefixes: list[tuple[str, int]],
    min_train: int = 40,
) -> dict:
    y = y.astype(float)
    results = {"persistence": [], "groups": {}, "comparisons": {},
               "information": "one-step observed target lags; updated persistence; contemporaneous regressors",
               "feature_counts": {name: len(cols) + len(Y_LAGS) for name, cols in groups.items()}}
    all_cols = list(dict.fromkeys(col for cols in groups.values() for col in cols))
    common_X, common_y = design(y, x_full[all_cols])
    eligible = common_y.index[np.isfinite(common_X.to_numpy(float)).all(axis=1) & np.isfinite(common_y.to_numpy(float))]
    for name, cols in groups.items():
        results["groups"][name] = []
        x = x_full[cols] if cols else pd.DataFrame(index=y.index)
        for blk in blocks:
            tr = eligible[eligible < blk[0]]
            if len(tr) < min_train:
                raise ValueError(f"Insufficient common training sample: {name}, {blk[0]}, {len(tr)}")
            test = blk.intersection(eligible)
            if len(test) != len(blk):
                raise ValueError(f"Incomplete common evaluation block: {name}, {list(blk.difference(test))}")
            alpha = pick_alpha(y, x, tr, max(len(blk), 1), min_train=min_train)
            hat = roll_ridge(y, x, tr, blk, alpha, min_obs=min_train)
            pers = one_step_persistence(y, blk)
            if not np.isfinite(hat).all() or not np.isfinite(pers).all():
                raise ValueError(f"Nonfinite prediction in common block: {name}, {blk[0]}")
            yb = y.reindex(blk)
            for lab, n in prefixes:
                take = min(n, len(blk))
                rec = {
                    "block_start": str(pd.Timestamp(blk[0]).date()),
                    "block_end": str(pd.Timestamp(blk[-1]).date()),
                    "horizon": lab,
                    "evaluation_block": lab,
                    "dates": [str(pd.Timestamp(t).date()) for t in blk[:take]],
                    "actual": yb.iloc[:take].tolist(),
                    "predicted": hat[:take].tolist(),
                    "training_dates": [str(pd.Timestamp(t).date()) for t in tr],
                    "information": "one-step; observed lags updated within block",
                    "alpha": alpha,
                    **_score(yb.iloc[:take], hat[:take]),
                }
                rec_p = {
                    "block_start": rec["block_start"],
                    "block_end": rec["block_end"],
                    "horizon": lab,
                    "evaluation_block": lab,
                    "dates": rec["dates"],
                    "actual": rec["actual"],
                    "predicted": pers[:take].tolist(),
                    **_score(yb.iloc[:take], pers[:take]),
                }
                results["groups"][name].append(rec)
                if not any(
                    r["block_start"] == rec_p["block_start"] and r["horizon"] == lab
                    for r in results["persistence"]
                ):
                    results["persistence"].append(rec_p)
    for name in groups:
        control = "y_seasonal" if name == "y_seasonal_exp" else ("y_list" if name == "y_list_exp" else "y_only")
        if name == "y_dprod_dqty":
            control = "y_dqty"
        elif name == "y_pbr_gap":
            control = "y_pbr" if "y_pbr" in groups else "y_pbr0"
        if name == control or control not in results["groups"]:
            continue
        results["comparisons"][name] = {
            lab: {"control_group": control, **summarize(results["groups"][name], results["groups"][control], lab)}
            for lab, _ in prefixes
        }
    return results


def eval_groups(
    y: pd.Series,
    x_full: pd.DataFrame,
    blocks: list[pd.Index],
    prefixes: list[tuple[str, int]],
    min_train: int = 40,
) -> dict:
    return eval_named_groups(y, x_full, GROUPS, blocks, prefixes, min_train=min_train)


def summarize(block_rows: list[dict], pers_rows: list[dict], horizon: str) -> dict:
    g = [r for r in block_rows if r["horizon"] == horizon]
    p = [r for r in pers_rows if r["horizon"] == horizon]
    if not g or not p:
        return {}
    def key(record: dict) -> tuple:
        return record["block_start"], record["block_end"], record["horizon"]
    controls = {key(r): r for r in p}
    if set(map(key, g)) != set(controls):
        raise ValueError("Candidate/control evaluation blocks differ")
    p = [controls[key(r)] for r in g]
    for candidate, control in zip(g, p):
        if candidate["n"] != control["n"] or (candidate.get("dates") is not None and control.get("dates") is not None and candidate["dates"] != control["dates"]):
            raise ValueError("Candidate/control observations differ")
    med_g = float(np.nanmedian([r["RMSE"] for r in g]))
    med_p = float(np.nanmedian([r["RMSE"] for r in p]))
    med_mae_g = float(np.nanmedian([r["MAE"] for r in g]))
    med_mae_p = float(np.nanmedian([r["MAE"] for r in p]))
    wins = 0
    for a, b in zip(g, p):
        if a["RMSE"] < b["RMSE"]:
            wins += 1
    rel = (med_p - med_g) / med_p if med_p else math.nan
    promote = rel >= 0.05 and wins > len(g) / 2 and med_mae_g <= med_mae_p
    return {
        "horizon": horizon,
        "median_RMSE": med_g,
        "persistence_median_RMSE": med_p,
        "rel_RMSE_vs_pers": rel,
        "median_MAE": med_mae_g,
        "persistence_median_MAE": med_mae_p,
        "blocks_better_RMSE": wins,
        "n_blocks": len(g),
        "worst_block_RMSE": max(r["RMSE"] for r in g),
        "block_comparisons": [{"block_start": a["block_start"], "block_end": a["block_end"], "candidate_RMSE": a["RMSE"], "control_RMSE": b["RMSE"], "candidate_MAE": a["MAE"], "control_MAE": b["MAE"], "n": a["n"]} for a,b in zip(g,p)],
        "promote_ge_5pct": promote,
    }


def main() -> None:
    root = find_project_root()
    path = sqlite_file(CURRENT_FREEZE, root)
    frames = add_exposure_variants(load_frames_at(path, root))
    daily = frames["daily"]
    price = frames["price_week"]
    monthly = frames["monthly"]
    fin = frames["fin"]

    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "experiment": "one-step Ridge with realized y lags and realized exposure (R$ millions)",
        "sqlite": CURRENT_FREEZE,
        "sha256": CURRENT_SHA256,
        "information": "contemporaneous (realized exposure on the horizon)",
        "alphas": list(ALPHAS),
        "vectors": {},
    }

    print("mercado PETR4")
    mkt_blocks = trailing_blocks(daily.index, e3.MKT_TRAIN_END, 6, 21)
    mkt = eval_groups(
        daily["petr4"],
        daily[["prod_mn", "prod_gas_mn", "prod_die_mn", "dprod_mn"]],
        mkt_blocks,
        [("5d", 5), ("21d", 21)],
    )
    report["vectors"]["mercado_PETR4"] = {
        "blocks": [f"{b[0].date()}..{b[-1].date()}" for b in mkt_blocks],
        "summary": {
            g: {h: summarize(rows, mkt["persistence"], h) for h in ("5d", "21d")}
            for g, rows in mkt["groups"].items()
        },
        "persistence_summary": {h: summarize(mkt["persistence"], mkt["persistence"], h) for h in ("5d", "21d")},
        "rows": mkt,
    }

    print("preço")
    price_blocks = trailing_blocks(price.index, e3.PRICE_TRAIN_END, 4, 8)
    price_out = {}
    for col, lab in [
        ("anp_gas", "ANP gasolina"),
        ("anp_die", "ANP diesel"),
        ("pbr_gas", "Petrobras gasolina"),
        ("pbr_die", "Petrobras diesel"),
    ]:
        print(" ", lab)
        ev = eval_groups(
            price[col],
            price[["prod_mn", "prod_gas_mn", "prod_die_mn", "dprod_mn"]],
            price_blocks,
            [("4w", 4), ("8w", 8)],
        )
        price_out[lab] = {
            "summary": {
                g: {h: summarize(rows, ev["persistence"], h) for h in ("4w", "8w")}
                for g, rows in ev["groups"].items()
            },
            "rows": ev,
        }
    report["vectors"]["preco"] = {
        "blocks": [f"{b[0].date()}..{b[-1].date()}" for b in price_blocks],
        "targets": price_out,
    }

    print("atividade")
    act_blocks = trailing_blocks(monthly.index, e3.ACT_TRAIN_END, 4, 3)
    act_out = {}
    for col, lab in [
        ("abcr_heavy", "tráfego pesado"),
        ("pim", "indústria"),
        ("pmc", "varejo"),
        ("unemp", "desemprego"),
    ]:
        print(" ", lab)
        ev = eval_groups(
            monthly[col],
            monthly[["prod_mn", "prod_gas_mn", "prod_die_mn", "dprod_mn"]],
            act_blocks,
            [("1m", 1), ("3m", 3)],
            min_train=24,
        )
        act_out[lab] = {
            "summary": {
                g: {h: summarize(rows, ev["persistence"], h) for h in ("1m", "3m")}
                for g, rows in ev["groups"].items()
            },
            "rows": ev,
        }
    report["vectors"]["atividade"] = {
        "blocks": [f"{b[0].date()}..{b[-1].date()}" for b in act_blocks],
        "targets": act_out,
    }

    print("companhia (descritivo, 4 trimestres)")
    fin_idx = fin.index
    # last four quarters before 2Q26
    before = fin_idx[fin_idx <= e3.COMP_TRAIN_END]
    q_blocks = [before[-k : -k + 1] if k > 1 else before[-1:] for k in range(4, 0, -1)]
    q_blocks = [b for b in q_blocks if len(b)]
    comp_out = {}
    xfin = fin[["prod_pbr_mn", "prod_pbr_gas_mn", "prod_pbr_die_mn"]].copy()
    xfin["dprod_mn"] = fin["prod_pbr_mn"].diff()
    # map group names onto company columns
    global GROUPS
    saved = dict(GROUPS)
    GROUPS = {
        "y_only": [],
        "y_prod": ["prod_pbr_mn"],
        "y_fuels": ["prod_pbr_gas_mn", "prod_pbr_die_mn"],
        "y_dprod": ["dprod_mn"],
    }
    for col, lab in [
        ("diesel_mbpd", "diesel mbpd"),
        ("gasoline_mbpd", "gasolina mbpd"),
        ("rtm_sales_revenue_rsmn", "receita RT&M"),
        ("rtm_gross_profit_rsmn", "lucro bruto RT&M"),
        ("rtm_gross_margin_pct", "margem RT&M"),
    ]:
        print(" ", lab)
        ev = eval_groups(
            fin[col],
            xfin,
            q_blocks,
            [("1q", 1)],
            min_train=8,
        )
        comp_out[lab] = {
            "summary": {
                g: {h: summarize(rows, ev["persistence"], h) for h in ("1q",)}
                for g, rows in ev["groups"].items()
            },
            "descriptive": True,
            "rows": ev,
        }
    GROUPS = saved
    report["vectors"]["companhia"] = {
        "blocks": [f"{b[0].date()}" for b in q_blocks],
        "note": "four one-quarter blocks before 2Q26; no promotion rule",
        "targets": comp_out,
    }

    out = results_dir(root) / "etapa4_prod_contrib.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
