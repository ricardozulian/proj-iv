"""Financial-history baselines on 82 RT&M quarters.

Bounded ARIMA/SARIMA grid, additive damped exponential smoothing,
persistence, and seasonal persistence (s=4). Fits use statsmodels.
Does not overwrite etapa3_metrics.json.
Writes results/etapa4_finance_baseline.json.
"""

from __future__ import annotations

import json
import math
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np
import pandas as pd
from sqlalchemy import text

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from etapa4_data import CURRENT_FREEZE, engine_for, sqlite_file
from paths import results_dir
from db_access import find_project_root


def _silence_statsmodels() -> None:
    """Workers do not inherit the parent warning filter."""
    try:
        from statsmodels.tools.sm_exceptions import (
            ConvergenceWarning,
            HessianInversionWarning,
            ValueWarning,
        )
    except Exception:  # pragma: no cover
        ConvergenceWarning = UserWarning
        HessianInversionWarning = UserWarning
        ValueWarning = UserWarning
    warnings.filterwarnings("ignore", category=ConvergenceWarning)
    warnings.filterwarnings("ignore", category=HessianInversionWarning)
    warnings.filterwarnings("ignore", category=ValueWarning)
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    warnings.simplefilter("ignore")


_silence_statsmodels()

TARGETS = (
    ("rtm_sales_revenue_rsmn", "receita RT&M"),
    ("rtm_gross_profit_rsmn", "lucro bruto RT&M"),
    ("rtm_gross_margin_pct", "margem RT&M"),
)

NAIVE_METHODS = ("persistence", "seasonal_s4")
ES_METHODS = ("ses", "holt_damped", "hw_add_damped_s4")


class FitFailure(Exception):
    def __init__(self, method: str, window, origin: int, reason: str):
        super().__init__(f"{method} window={window} origin={origin}: {reason}")
        self.method = method
        self.window = window
        self.origin = int(origin)
        self.reason = reason


def arima_orders() -> list[tuple[int, int, int]]:
    out = []
    for d in (0, 1):
        for p in (0, 1):
            for q in (0, 1):
                if p + q <= 1:
                    out.append((p, d, q))
    return out


def sarima_orders() -> list[tuple[int, int, int, int, int, int]]:
    out = []
    for p, d, q in arima_orders():
        for D in (0, 1):
            if d + D > 1:
                continue
            for P in (0, 1):
                for Q in (0, 1):
                    if P + Q <= 1:
                        out.append((p, d, q, P, D, Q))
    return out


def arima_name(p: int, d: int, q: int) -> str:
    return f"arima_{p}_{d}_{q}"


def sarima_name(p: int, d: int, q: int, P: int, D: int, Q: int) -> str:
    return f"sarima_{p}_{d}_{q}_{P}_{D}_{Q}_4"


def enumerate_methods() -> list[str]:
    methods = list(NAIVE_METHODS)
    methods.extend(arima_name(*o) for o in arima_orders())
    methods.extend(sarima_name(*o) for o in sarima_orders())
    methods.extend(ES_METHODS)
    return methods


def enumerate_configs() -> list[tuple[str, int | None]]:
    return [(method, window) for method in enumerate_methods() for window in (None, 40)]


def grid_spec() -> dict:
    return {
        "persistence": list(NAIVE_METHODS),
        "arima_orders": [list(o) for o in arima_orders()],
        "sarima_orders": [list(o) for o in sarima_orders()],
        "sarima_seasonal_period": 4,
        "exponential_smoothing": list(ES_METHODS),
        "errors": "additive",
        "windows": [None, 40],
        "n_methods": len(enumerate_methods()),
        "n_configs": len(enumerate_configs()),
        "constraints": {
            "arima": "p,q in {0,1}, p+q <= 1, d in {0,1}",
            "sarima": "same nonseasonal; P,Q in {0,1}, P+Q <= 1, D in {0,1}, d+D <= 1, s=4",
            "es": "local level; damped additive trend; damped additive trend + additive seasonal s=4",
        },
    }


def _score(y, yhat) -> dict:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.isfinite(y) & np.isfinite(yhat)
    y, yhat = y[mask], yhat[mask]
    if y.size == 0:
        return {"MAE": math.nan, "RMSE": math.nan, "n": 0}
    err = y - yhat
    return {"MAE": float(np.mean(np.abs(err))), "RMSE": float(np.sqrt(np.mean(err * err))), "n": int(y.size)}


def load_rtm(root: Path) -> pd.DataFrame:
    engine = engine_for(sqlite_file(CURRENT_FREEZE, root))
    df = pd.read_sql_query(
        text(
            "SELECT year, quarter_num, quarter, "
            "rtm_sales_revenue_rsmn, rtm_gross_profit_rsmn, rtm_gross_margin_pct "
            "FROM pbr_quarterly_diesel_gasoline ORDER BY year, quarter_num"
        ),
        engine,
    )
    df["qkey"] = df["year"] * 4 + df["quarter_num"]
    return df.set_index("qkey").sort_index()


def origins(year_from: int, q_from: int, year_to: int, q_to: int) -> list[int]:
    start = year_from * 4 + q_from
    end = year_to * 4 + q_to
    return list(range(start, end + 1))


def prepare_past(hist: pd.Series, origin: int, window: int | None) -> pd.Series:
    past = hist.loc[hist.index < origin].dropna()
    if window is not None:
        past = past.iloc[-window:]
    return past


def _converged(fit) -> bool:
    ret = getattr(fit, "mle_retvals", None)
    if ret is None:
        return True
    if isinstance(ret, dict):
        if "converged" in ret:
            return bool(ret["converged"])
        if "success" in ret:
            return bool(ret["success"])
        return True
    if hasattr(ret, "success"):
        return bool(ret.success)
    return True


def _unscale(value: float, center: float, scale: float) -> float:
    hat = float(value) * scale + center
    if not np.isfinite(hat):
        raise ValueError("non-finite forecast")
    return hat


def _fit_arima(scaled: np.ndarray, order: tuple[int, int, int]):
    from statsmodels.tsa.arima.model import ARIMA

    _silence_statsmodels()
    p, d, q = order
    trend = "c" if d == 0 else "n"
    model = ARIMA(scaled, order=order, trend=trend, enforce_stationarity=False, enforce_invertibility=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = model.fit(method_kwargs={"maxiter": 200})
        if not _converged(fit):
            fit = model.fit(method_kwargs={"method": "powell", "maxiter": 500})
    if not _converged(fit):
        raise ValueError(f"ARIMA{order} did not converge")
    return fit


def _fit_sarima(scaled: np.ndarray, order, seasonal):
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    p, d, q = order
    P, D, Q, s = seasonal
    trend = "c" if d == 0 and D == 0 else "n"
    model = SARIMAX(
        scaled,
        order=order,
        seasonal_order=seasonal,
        trend=trend,
        enforce_stationarity=False,
        enforce_invertibility=False,
    )
    _silence_statsmodels()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = model.fit(disp=False, maxiter=200)
        if not _converged(fit):
            fit = model.fit(method="powell", disp=False, maxiter=500)
    if not _converged(fit):
        raise ValueError(f"SARIMA{order}x{seasonal} did not converge")
    return fit


def _fit_es(scaled: np.ndarray, method: str):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing, SimpleExpSmoothing

    if method == "ses":
        model = SimpleExpSmoothing(scaled, initialization_method="estimated")
    elif method == "holt_damped":
        model = ExponentialSmoothing(
            scaled, trend="add", damped_trend=True, initialization_method="estimated"
        )
    elif method == "hw_add_damped_s4":
        if len(scaled) < 8:
            raise ValueError("Holt-Winters needs at least 8 observations")
        model = ExponentialSmoothing(
            scaled,
            trend="add",
            damped_trend=True,
            seasonal="add",
            seasonal_periods=4,
            initialization_method="estimated",
        )
    else:
        raise ValueError(method)
    _silence_statsmodels()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = model.fit(optimized=True)
    if not _converged(fit):
        model2 = (
            SimpleExpSmoothing(scaled, initialization_method="heuristic")
            if method == "ses"
            else ExponentialSmoothing(
                scaled,
                trend="add",
                damped_trend=True,
                seasonal=("add" if method == "hw_add_damped_s4" else None),
                seasonal_periods=(4 if method == "hw_add_damped_s4" else None),
                initialization_method="heuristic",
            )
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = model2.fit(optimized=True)
    if not _converged(fit):
        raise ValueError(f"{method} did not converge")
    return fit


def forecast_with_meta(hist: pd.Series, origin: int, method: str, window: int | None) -> tuple[float, dict]:
    past = prepare_past(hist, origin, window)
    meta = {
        "method": method,
        "window": window,
        "origin": int(origin),
        "train_start": int(past.index.min()) if len(past) else None,
        "train_end": int(past.index.max()) if len(past) else None,
        "n_train": int(len(past)),
    }
    if past.empty:
        raise FitFailure(method, window, origin, "empty training window")
    try:
        if method == "persistence":
            hat = float(past.iloc[-1])
            return hat, meta
        if method == "seasonal_s4":
            lag = origin - 4
            hat = float(past.loc[lag]) if lag in past.index else float(past.iloc[-1])
            return hat, meta
        values = past.to_numpy(float)
        center, scale = float(values.mean()), max(float(values.std()), 1e-12)
        scaled = (values - center) / scale
        if method.startswith("arima_"):
            p, d, q = (int(x) for x in method.split("_")[1:4])
            fit = _fit_arima(scaled, (p, d, q))
            hat = _unscale(fit.forecast(1)[0], center, scale)
            return hat, meta
        if method.startswith("sarima_"):
            p, d, q, P, D, Q = (int(x) for x in method.split("_")[1:7])
            fit = _fit_sarima(scaled, (p, d, q), (P, D, Q, 4))
            hat = _unscale(fit.forecast(1)[0], center, scale)
            return hat, meta
        if method in ES_METHODS:
            fit = _fit_es(scaled, method)
            hat = _unscale(fit.forecast(1)[0], center, scale)
            return hat, meta
        raise ValueError(f"unknown method {method}")
    except FitFailure:
        raise
    except Exception as exc:
        raise FitFailure(method, window, origin, f"{type(exc).__name__}: {exc}") from exc


def forecast_one(hist: pd.Series, origin: int, method: str, window: int | None) -> float:
    hat, _meta = forecast_with_meta(hist, origin, method, window)
    return hat


def eval_block(series: pd.Series, keys: list[int], method: str, window: int | None) -> dict:
    y, yhat = [], []
    rows = []
    failures = []
    required = []
    for origin in keys:
        if origin not in series.index or not np.isfinite(series.loc[origin]):
            continue
        required.append(int(origin))
        try:
            hat, meta = forecast_with_meta(series, origin, method, window)
        except FitFailure as exc:
            failures.append(
                {
                    "method": method,
                    "window": window,
                    "origin": exc.origin,
                    "reason": exc.reason,
                }
            )
            continue
        actual = float(series.loc[origin])
        y.append(actual)
        yhat.append(hat)
        rec = {"qkey": origin, "actual": actual, "hat": hat}
        rec.update(meta)
        rows.append(rec)
    out = _score(y, yhat)
    out["method"] = method
    out["window"] = window
    out["points"] = rows
    out["n_required"] = len(required)
    out["n_failed"] = len(failures)
    out["failures"] = failures
    if failures:
        out["status"] = "failed"
        out["RMSE"] = math.nan
        out["MAE"] = math.nan
        out["n"] = 0
    else:
        out["status"] = "ok"
    return out


def _compact(block: dict) -> dict:
    keep = ("method", "window", "RMSE", "MAE", "n", "n_required", "n_failed", "status")
    return {k: block[k] for k in keep}


def _window_key(window) -> str:
    return "None" if window is None else str(window)


def comparison_vs_control(candidate: dict, control: dict) -> dict:
    by_c = {p["qkey"]: p for p in control.get("points") or []}
    paired = []
    for p in candidate.get("points") or []:
        q = p["qkey"]
        if q not in by_c:
            continue
        if not np.isfinite(p["hat"]) or not np.isfinite(by_c[q]["hat"]):
            continue
        paired.append((p["actual"], p["hat"], by_c[q]["hat"]))
    if not paired:
        return {"n": 0, "RMSE": math.nan, "control_RMSE": math.nan, "rel_RMSE": math.nan, "meets_rule": False}
    y = np.array([a[0] for a in paired], float)
    hat = np.array([a[1] for a in paired], float)
    ctrl = np.array([a[2] for a in paired], float)
    cand = _score(y, hat)
    base = _score(y, ctrl)
    rel = (base["RMSE"] - cand["RMSE"]) / base["RMSE"] if base["RMSE"] else math.nan
    n_better = int(np.sum(np.abs(y - hat) < np.abs(y - ctrl)))
    mae_ok = cand["MAE"] <= base["MAE"] if np.isfinite(cand["MAE"]) and np.isfinite(base["MAE"]) else False
    majority = n_better > len(paired) / 2
    meets = bool(np.isfinite(rel) and rel >= 0.05 and majority and mae_ok)
    return {
        "n": cand["n"],
        "RMSE": cand["RMSE"],
        "MAE": cand["MAE"],
        "control_RMSE": base["RMSE"],
        "control_MAE": base["MAE"],
        "rel_RMSE": rel,
        "n_better_abs_err": n_better,
        "majority_origins": majority,
        "mae_not_worse": mae_ok,
        "meets_rule": meets,
        "qkeys": [p["qkey"] for p in candidate["points"] if p["qkey"] in by_c],
    }


def _eval_config_job(payload: tuple) -> dict:
    _silence_statsmodels()
    values, index, keys, method, window = payload
    series = pd.Series(values, index=index)
    return eval_block(series, list(keys), method, window)


def eval_many(series: pd.Series, keys: list[int], configs: list[tuple[str, int | None]], workers: int) -> list[dict]:
    if workers <= 1 or len(configs) == 1:
        return [eval_block(series, keys, method, window) for method, window in configs]
    values = series.to_numpy(dtype=float)
    index = series.index.to_numpy()
    key_tuple = tuple(keys)
    payloads = [(values, index, key_tuple, method, window) for method, window in configs]
    blocks = [None] * len(configs)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_eval_config_job, payload): i for i, payload in enumerate(payloads)}
        for fut in as_completed(futures):
            blocks[futures[fut]] = fut.result()
    return list(blocks)


def load_locked_baselines(root: Path | None = None) -> dict[str, dict]:
    root = root or find_project_root()
    path = results_dir(root) / "etapa4_finance_baseline.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for lab, node in data["targets"].items():
        w = node["winner"]
        out[lab] = {"method": w["method"], "window": w["window"], "select_RMSE": w.get("select_RMSE")}
    return out


def main() -> None:
    root = find_project_root()
    df = load_rtm(root)
    select = origins(2019, 1, 2021, 4)
    eval_mid = origins(2022, 1, 2026, 1)
    eval_pre = origins(2022, 1, 2025, 4)
    q226 = 2026 * 4 + 2
    configs = enumerate_configs()
    workers = int(os.environ.get("ETAPA4_WORKERS", "4"))
    spec = grid_spec()
    spec["workers"] = workers
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sqlite": CURRENT_FREEZE,
        "n_quarters": int(len(df)),
        "select_window": "1Q19-4Q21",
        "eval_window": "1Q22-1Q26",
        "eval_pre_2026": "1Q22-4Q25",
        "legacy": "2Q26",
        "grid": spec,
        "failures": [],
        "targets": {},
        "interpretation": (
            "Persistence and seasonal persistence do not measure long-history benefit; "
            "their full-history and 40-quarter forecasts stay identical. "
            "ARIMA, SARIMA and damped exponential smoothing fit each training window. "
            "Selection uses 1Q19-4Q21 only; 1Q22-1Q26 rankings are reported and do not reselect. "
            "Failed configurations are listed and excluded from selection; origins are not dropped from a scored block."
        ),
        "numerics": (
            "Standardize using each past training window only; undo scaling after forecast. "
            "ARIMA/SARIMA use L-BFGS and retry Powell if needed. "
            "Exponential smoothing uses estimated initialization and retries heuristic. "
            "An unresolved fit records the configuration, origin and reason and marks the configuration failed."
        ),
    }
    all_failures = []
    for col, lab in TARGETS:
        series = df[col].astype(float)
        print(f"{lab}: selection {len(configs)} configs, workers={workers}", flush=True)
        selection = eval_many(series, select, configs, workers)
        for block in selection:
            if block["status"] == "failed":
                all_failures.extend(block["failures"])
                print(f"  FAIL {lab} {block['method']} window={block['window']} n_failed={block['n_failed']}", flush=True)
            else:
                print(f"  SEL  {lab} {block['method']} window={block['window']} RMSE={block['RMSE']:.4f}", flush=True)
        successful = [r for r in selection if r["status"] == "ok"]
        if not successful:
            raise RuntimeError(f"no successful financial configuration for {lab}")
        ranked = sorted(successful, key=lambda r: r["RMSE"])
        winner = ranked[0]
        locked = (winner["method"], winner["window"])
        mid = eval_block(series, eval_mid, locked[0], locked[1])
        pre = eval_block(series, eval_pre, locked[0], locked[1])
        legacy = eval_block(series, [q226], locked[0], locked[1])
        if mid["status"] != "ok" or pre["status"] != "ok" or legacy["status"] != "ok":
            all_failures.extend(mid["failures"] + pre["failures"] + legacy["failures"])
            raise RuntimeError(f"locked configuration failed on evaluation for {lab}: {locked}")
        pers_mid = eval_block(series, eval_mid, "persistence", None)
        pers_pre = eval_block(series, eval_pre, "persistence", None)
        print(f"{lab}: eval ranking {len(configs)} configs", flush=True)
        eval_blocks = eval_many(series, eval_mid, configs, workers)
        eval_rank_rows = []
        history = {}
        for ev in eval_blocks:
            if ev["status"] == "failed":
                all_failures.extend(ev["failures"])
            eval_rank_rows.append(_compact(ev))
            history.setdefault(ev["method"], {})
            history[ev["method"]][_window_key(ev["window"])] = _compact(ev)
        eval_ok = [r for r in eval_rank_rows if r["status"] == "ok"]
        eval_ranked = sorted(eval_ok, key=lambda r: r["RMSE"])
        report["targets"][lab] = {
            "column": col,
            "selection_1Q19_4Q21": [_compact(r) for r in selection],
            "winner": {
                "method": locked[0],
                "window": locked[1],
                "select_RMSE": winner["RMSE"],
                "select_MAE": winner["MAE"],
                "select_n": winner["n"],
            },
            "eval_1Q22_1Q26": _compact(mid),
            "eval_1Q22_4Q25": _compact(pre),
            "legacy_2Q26": _compact(legacy),
            "eval_ranking_1Q22_1Q26": eval_ranked,
            "comparison_vs_persistence": {
                "eval_1Q22_1Q26": comparison_vs_control(mid, pers_mid),
                "eval_1Q22_4Q25": comparison_vs_control(pre, pers_pre),
            },
            "eval_points": mid["points"],
            "eval_pre_2026_points": pre["points"],
            "legacy_points": legacy["points"],
            "selection_points": winner["points"],
            "history_window_comparison": history,
        }
        print(
            f"{lab}: winner {locked} select RMSE={winner['RMSE']:.3f} "
            f"1Q22-1Q26 RMSE={mid['RMSE']:.3f} 1Q22-4Q25 RMSE={pre['RMSE']:.3f} "
            f"2Q26 hat={legacy['points'][0]['hat'] if legacy['points'] else None}"
        )
    report["failures"] = all_failures
    report["n_failures"] = len(all_failures)
    out = results_dir(root) / "etapa4_finance_baseline.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {out} failures={len(all_failures)}")


if __name__ == "__main__":
    main()
