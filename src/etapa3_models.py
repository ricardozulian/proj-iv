"""Etapa 3 forecast runner (frozen recorte).

Every in-grid model reads the target against contemporaneous PPI × volume
(`prod` / `prod_pbr`). Naive is the lecture dummy.

    Mercado (day):    naive, SARIMAX+prod, LSTM+prod, TimesFM+prod
    Preço (week):     naive, SARIMAX+prod, Prophet+prod
    Atividade (month): naive, SARIMAX+prod, Prophet+prod
    Companhia (quarter): naive, SARIMAX+prod_pbr

    python src/etapa3_models.py
    python src/etapa3_models.py --only naive,lstm
    python src/etapa3_models.py --only company

On Windows the OpenBLAS stack aborts statsmodels, pmdarima, Prophet and
matplotlib raster. This module then fits naive and LSTM. SARIMAX, Prophet
and TimesFM 3.0 run on the MacBook M4 from the same folder.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import platform
import sys
import traceback
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from db_access import find_project_root, read_engine
from paths import (
    ensure_output_dirs,
    figures_eda_dir,
    figures_forecasts_dir,
    forecasts_path,
    metrics_path,
)

LITERS_PER_M3 = 1000.0
LITERS_PER_MBPD = 1000.0 * 159.0
SEED = 19

MKT_TRAIN_END = pd.Timestamp("2026-08-19")
MKT_TEST_END = pd.Timestamp("2026-09-18")
PRICE_TRAIN_END = pd.Timestamp("2026-07-19")
PRICE_TEST_END = pd.Timestamp("2026-09-13")
ACT_TRAIN_END = pd.Timestamp("2026-04-01")
ACT_TEST_END = pd.Timestamp("2026-07-01")
COMP_TRAIN_END = pd.Timestamp("2026-03-31")

CHECKPOINT = "google/timesfm-3.0-pytorch"

WIN_DEFAULT = ("naive", "lstm")
FULL_DEFAULT = ("naive", "lstm", "sarimax", "prophet", "timesfm")
IN_SCOPE_MODELS = frozenset(
    {"naive", "sarimax", "prophet", "lstm", "timesfm", "timesfm_cov"}
)


def _sql(engine, q: str) -> pd.DataFrame:
    return pd.read_sql_query(q, engine)


def score(y, yhat) -> dict[str, float]:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.isfinite(y) & np.isfinite(yhat)
    y, yhat = y[mask], yhat[mask]
    if y.size == 0:
        return {"MAE": math.nan, "MSE": math.nan, "RMSE": math.nan}
    err = y - yhat
    mse = float(np.mean(err * err))
    return {"MAE": float(np.mean(np.abs(err))), "MSE": mse, "RMSE": float(np.sqrt(mse))}


def after(series: pd.Series | pd.DataFrame, end: pd.Timestamp):
    return series.loc[series.index > end]


def row(vector: str, target: str, model: str, horizon: str, y, yhat, extra: dict | None = None) -> dict:
    out = {"vector": vector, "target": target, "model": model, "horizon": horizon}
    out.update(score(y, yhat))
    if extra:
        out.update(extra)
    return out


def load_payload(root: Path) -> dict:
    path = metrics_path(root)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"rows": [], "notes": [], "forecasts": {}, "meta": {}}


def merge_rows(old: list[dict], new: list[dict]) -> list[dict]:
    key = lambda r: (r["vector"], r["target"], r["model"], r["horizon"])
    by = {key(r): r for r in old}
    for r in new:
        by[key(r)] = r
    return list(by.values())


def save_payload(root: Path, payload: dict, forecasts: dict) -> None:
    ensure_output_dirs(root)
    payload = dict(payload)
    payload["forecasts_file"] = str(forecasts_path(root).name)
    metrics_path(root).write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    old: dict = {}
    fp = forecasts_path(root)
    if fp.exists():
        old = json.loads(fp.read_text(encoding="utf-8"))
    _merge_fc(old, forecasts)
    fp.write_text(json.dumps(old, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def dates_iso(idx) -> list[str]:
    return [pd.Timestamp(t).strftime("%Y-%m-%d") for t in idx]


# ---------------------------------------------------------------------------
# Data (same construction as the etapa3 notebook)
# ---------------------------------------------------------------------------

def load_frames(root: Path | None = None) -> dict[str, Any]:
    root = root or find_project_root()
    engine = read_engine(root)

    ppi = _sql(
        engine,
        "SELECT report_date, pbr_gas_R, pbr_gas_pct, pbr_die_R, pbr_die_pct "
        "FROM ppi_daily ORDER BY report_date",
    )
    ppi["report_date"] = pd.to_datetime(ppi["report_date"])
    ppi = ppi.set_index("report_date").sort_index()

    eq = _sql(engine, "SELECT tradedate, price_last FROM equity_daily WHERE ticker='PETR4' ORDER BY tradedate")
    eq["tradedate"] = pd.to_datetime(eq["tradedate"])
    eq = eq.set_index("tradedate").sort_index()["price_last"]

    anp_sales = _sql(engine, "SELECT product, month, volume_m3 FROM anp_fuel_sales ORDER BY month, product")
    anp_sales["month"] = pd.to_datetime(anp_sales["month"])
    anp_wide = anp_sales.pivot(index="month", columns="product", values="volume_m3")
    anp_wide.columns = [f"anp_{c}_m3" for c in anp_wide.columns]

    def weekly(table: str, col: str) -> pd.DataFrame:
        d = _sql(engine, f"SELECT week_start, avg_price_rs_l AS {col} FROM {table}")
        d["week_start"] = pd.to_datetime(d["week_start"])
        return d.set_index("week_start").sort_index()

    price_week = (
        weekly("anp_distributor_weekly_gasoline", "anp_gas")
        .join(weekly("anp_distributor_weekly_diesel", "anp_die"), how="outer")
        .join(weekly("petrobras_distributor_weekly_gasoline", "pbr_gas"), how="outer")
        .join(weekly("petrobras_distributor_weekly_diesel", "pbr_die"), how="outer")
        .sort_index()
    )
    week_idx = pd.date_range(price_week.index.min(), PRICE_TEST_END, freq="W-MON")
    price_week = price_week.reindex(week_idx).ffill()

    abcr = _sql(engine, "SELECT month, vehicle_type, traffic_index FROM abcr_traffic_index")
    abcr["month"] = pd.to_datetime(abcr["month"])
    abcr_wide = abcr.pivot(index="month", columns="vehicle_type", values="traffic_index").sort_index()
    abcr_wide = abcr_wide.rename(columns={"light": "abcr_light", "heavy": "abcr_heavy", "total": "abcr_total"})

    ibge = _sql(engine, "SELECT indicator_code, month, value FROM ibge_indicators")
    ibge["month"] = pd.to_datetime(ibge["month"])
    ibge_wide = ibge.pivot(index="month", columns="indicator_code", values="value").sort_index()
    ibge_wide = ibge_wide.rename(columns={"6381": "unemp", "8880": "pmc", "8888": "pim"})

    fin = _sql(
        engine,
        "SELECT year, quarter_num, diesel_mbpd, gasoline_mbpd, "
        "diesel_revenue_rsmn, gasoline_revenue_rsmn, "
        "rtm_sales_revenue_rsmn, rtm_gross_profit_rsmn, rtm_gross_margin_pct, "
        "extraction_note FROM pbr_quarterly_diesel_gasoline "
        "WHERE year >= 2022 ORDER BY year, quarter_num",
    )
    fin["quarter_end"] = pd.to_datetime(
        fin.apply(lambda r: pd.Timestamp(int(r.year), int(r.quarter_num) * 3, 1) + pd.offsets.MonthEnd(0), axis=1)
    )
    fin = fin.set_index("quarter_end").sort_index()

    daily_idx = eq.index
    vol = pd.DataFrame(index=daily_idx)
    vol["month"] = vol.index.to_period("M").to_timestamp()
    vol = vol.join(anp_wide, on="month")
    last_gas = anp_wide["anp_gasolina_c_m3"].dropna().iloc[-1]
    last_die = anp_wide["anp_diesel_m3"].dropna().iloc[-1]
    vol["anp_gasolina_c_m3"] = vol["anp_gasolina_c_m3"].fillna(last_gas)
    vol["anp_diesel_m3"] = vol["anp_diesel_m3"].fillna(last_die)
    days = vol.index.to_series().dt.days_in_month
    vol["vol_gas_l"] = vol["anp_gasolina_c_m3"] * LITERS_PER_M3 / days
    vol["vol_die_l"] = vol["anp_diesel_m3"] * LITERS_PER_M3 / days

    pbr_daily = pd.DataFrame(index=daily_idx)
    pbr_daily["qend"] = pd.DatetimeIndex(pbr_daily.index.to_period("Q").end_time).normalize()
    pbr_daily = pbr_daily.join(fin[["diesel_mbpd", "gasoline_mbpd"]], on="qend")
    pbr_daily[["diesel_mbpd", "gasoline_mbpd"]] = pbr_daily[["diesel_mbpd", "gasoline_mbpd"]].ffill()

    daily = pd.DataFrame({"petr4": eq}, index=daily_idx)
    daily = daily.join(ppi[["pbr_gas_R", "pbr_die_R", "pbr_gas_pct", "pbr_die_pct"]])
    daily[["pbr_gas_R", "pbr_die_R", "pbr_gas_pct", "pbr_die_pct"]] = daily[
        ["pbr_gas_R", "pbr_die_R", "pbr_gas_pct", "pbr_die_pct"]
    ].ffill()
    daily["vol_gas_l"] = vol["vol_gas_l"]
    daily["vol_die_l"] = vol["vol_die_l"]
    daily["prod"] = daily["pbr_gas_R"] * daily["vol_gas_l"] + daily["pbr_die_R"] * daily["vol_die_l"]
    daily["stock"] = daily["prod"].cumsum()
    daily["prod_pbr"] = (
        daily["pbr_gas_R"] * pbr_daily["gasoline_mbpd"] * LITERS_PER_MBPD
        + daily["pbr_die_R"] * pbr_daily["diesel_mbpd"] * LITERS_PER_MBPD
    )
    daily["stock_pbr"] = daily["prod_pbr"].cumsum()

    ppi_w = daily[["pbr_gas_R", "pbr_die_R", "prod"]].resample("W-MON").mean()
    price_week = price_week.join(ppi_w, how="left")
    price_week[["pbr_gas_R", "pbr_die_R", "prod"]] = price_week[["pbr_gas_R", "pbr_die_R", "prod"]].ffill()

    monthly = pd.DataFrame(
        {
            "abcr_heavy": abcr_wide["abcr_heavy"],
            "pim": ibge_wide["pim"],
            "pmc": ibge_wide["pmc"],
            "unemp": ibge_wide["unemp"],
        }
    ).sort_index()
    monthly["prod"] = daily["prod"].resample("MS").sum()
    monthly = monthly.loc[:ACT_TEST_END]

    prod_q = daily["prod_pbr"].resample("QE-DEC").sum().rename("prod_pbr")
    fin = fin.join(prod_q)

    mkt_train = daily.loc[:MKT_TRAIN_END]
    mkt_test = after(daily, MKT_TRAIN_END).loc[:MKT_TEST_END]
    price_train = price_week.loc[:PRICE_TRAIN_END]
    price_test = after(price_week, PRICE_TRAIN_END).loc[:PRICE_TEST_END]
    act_train = monthly.loc[:ACT_TRAIN_END]
    act_test = after(monthly, ACT_TRAIN_END).loc[:ACT_TEST_END]
    comp_train = fin.loc[:COMP_TRAIN_END]
    comp_test = after(fin, COMP_TRAIN_END)

    return {
        "root": root,
        "daily": daily,
        "price_week": price_week,
        "monthly": monthly,
        "fin": fin,
        "mkt_train": mkt_train,
        "mkt_test": mkt_test,
        "price_train": price_train,
        "price_test": price_test,
        "act_train": act_train,
        "act_test": act_test,
        "comp_train": comp_train,
        "comp_test": comp_test,
    }


# ---------------------------------------------------------------------------
# SVG overlay (no matplotlib: raster savefig aborts on this Windows host)
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_overlay_svg(
    path: Path,
    title: str,
    ylabel: str,
    index: pd.Index,
    series: dict[str, np.ndarray],
    colors: dict[str, str] | None = None,
    origin_i: int | None = None,
    mark_all: set[str] | None = None,
) -> None:
    palette = ["#222222", "#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b"]
    names = list(series.keys())
    colors = colors or {n: palette[i % len(palette)] for i, n in enumerate(names)}
    mark_all = mark_all or set()
    n = len(index)
    if n == 0:
        return
    vals = np.concatenate([np.asarray(v, dtype=float) for v in series.values()])
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return
    lo, hi = float(vals.min()), float(vals.max())
    if hi - lo < 1e-9:
        hi = lo + 1.0
    pad = 0.06 * (hi - lo)
    lo, hi = lo - pad, hi + pad
    W, H, L, T, R, B = 900, 340, 60, 36, 20, 56
    pw, ph = W - L - R, H - T - B

    def xy(i: int, v: float) -> tuple[float, float]:
        x = L + (i / max(n - 1, 1)) * pw
        y = T + (1.0 - (v - lo) / (hi - lo)) * ph
        return x, y

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{L}" y="20" font-family="Segoe UI, Arial" font-size="14">{_esc(title)}</text>',
        f'<text x="12" y="{T + ph / 2:.1f}" font-family="Segoe UI, Arial" font-size="11" '
        f'transform="rotate(-90 12 {T + ph / 2:.1f})">{_esc(ylabel)}</text>',
        f'<line x1="{L}" y1="{T}" x2="{L}" y2="{T + ph}" stroke="#333" stroke-width="1"/>',
        f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="#333" stroke-width="1"/>',
    ]
    if origin_i is not None and 0 <= origin_i < n:
        ox = L + (origin_i / max(n - 1, 1)) * pw
        parts.append(
            f'<line x1="{ox:.1f}" y1="{T}" x2="{ox:.1f}" y2="{T + ph}" '
            'stroke="#999" stroke-width="1" stroke-dasharray="4 3"/>'
        )
    for name in names:
        arr = np.asarray(series[name], dtype=float)
        segs: list[list[str]] = []
        cur: list[str] = []
        for i, v in enumerate(arr):
            if np.isfinite(v):
                x, y = xy(i, float(v))
                cur.append(f"{x:.1f},{y:.1f}")
            elif cur:
                segs.append(cur)
                cur = []
        if cur:
            segs.append(cur)
        for pts in segs:
            if len(pts) == 1:
                cx, cy = pts[0].split(",")
                parts.append(
                    f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="{colors[name]}"/>'
                )
            else:
                parts.append(
                    f'<polyline points="{" ".join(pts)}" fill="none" stroke="{colors[name]}" stroke-width="1.6"/>'
                )
                if name in mark_all:
                    for pt in pts:
                        cx, cy = pt.split(",")
                        parts.append(
                            f'<circle cx="{cx}" cy="{cy}" r="2.4" fill="{colors[name]}"/>'
                        )
                else:
                    cx, cy = pts[-1].split(",")
                    parts.append(
                        f'<circle cx="{cx}" cy="{cy}" r="3.2" fill="{colors[name]}"/>'
                    )
    lx = L + 8
    ly = H - 18
    for name in names:
        parts.append(f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" fill="{colors[name]}"/>')
        parts.append(
            f'<text x="{lx + 16}" y="{ly}" font-family="Segoe UI, Arial" font-size="11">{_esc(name)}</text>'
        )
        lx += 16 + 7 * max(len(name), 4) + 18
    parts.append(
        f'<text x="{L}" y="{H - 4}" font-family="Segoe UI, Arial" font-size="10">'
        f'{pd.Timestamp(index[0]).strftime("%d/%m/%Y")} — '
        f'{pd.Timestamp(index[-1]).strftime("%d/%m/%Y")}</text>'
    )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def series_history_and_fan(
    y_tr: pd.Series,
    y_te: pd.Series,
    blob: dict,
    models: tuple[str, ...] = ("naive", "sarimax", "prophet"),
) -> tuple[pd.Index, dict[str, np.ndarray], int]:
    """Full actual history plus model hats fanning from the last train point."""
    y_tr = y_tr.astype(float)
    y_te = y_te.astype(float)
    y_all = pd.concat([y_tr, y_te])
    idx = y_all.index
    n_tr = len(y_tr)
    last = float(y_tr.iloc[-1])
    series: dict[str, np.ndarray] = {"real": y_all.to_numpy(dtype=float)}
    n_te = len(idx) - n_tr
    for name in models:
        if name not in blob:
            continue
        hat = np.asarray(blob[name], dtype=float)
        arr = np.full(len(idx), np.nan)
        if n_tr:
            arr[n_tr - 1] = last
        take = min(len(hat), n_te)
        if take:
            arr[n_tr : n_tr + take] = hat[:take]
        series[name] = arr
    origin_i = max(n_tr - 1, 0)
    return idx, series, origin_i


# ---------------------------------------------------------------------------
# Naive
# ---------------------------------------------------------------------------

def run_naive(frames: dict) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    fc: dict = {}

    ytr, yte = frames["mkt_train"]["petr4"], frames["mkt_test"]["petr4"]
    hat = np.full(len(yte), float(ytr.iloc[-1]))
    rows.append(row("mercado", "PETR4", "naive", "5d", yte.iloc[:5], hat[:5]))
    rows.append(row("mercado", "PETR4", "naive", "21d", yte, hat))
    fc["mercado_PETR4"] = {
        "dates": dates_iso(yte.index),
        "actual": [float(v) for v in yte.to_numpy()],
        "naive": [float(v) for v in hat],
    }

    for col, lab in [
        ("anp_gas", "ANP gasolina"),
        ("anp_die", "ANP diesel"),
        ("pbr_gas", "Petrobras gasolina"),
        ("pbr_die", "Petrobras diesel"),
    ]:
        tr, te = frames["price_train"][col].dropna(), frames["price_test"][col]
        hat = np.full(len(te), float(tr.iloc[-1]))
        rows.append(row("preço", lab, "naive", "4w", te.iloc[:4], hat[:4]))
        rows.append(row("preço", lab, "naive", "8w", te, hat))
        fc[f"preco_{col}"] = {
            "dates": dates_iso(te.index),
            "actual": [float(v) if np.isfinite(v) else None for v in te.to_numpy()],
            "naive": [float(v) for v in hat],
        }

    for col, lab in [
        ("abcr_heavy", "tráfego pesado"),
        ("pim", "indústria"),
        ("pmc", "varejo"),
        ("unemp", "desemprego"),
    ]:
        tr, te = frames["act_train"][col].dropna(), frames["act_test"][col]
        hat = np.full(len(te), float(tr.iloc[-1]))
        rows.append(row("atividade", lab, "naive", "1m", te.iloc[:1], hat[:1]))
        rows.append(row("atividade", lab, "naive", "3m", te, hat))
        fc[f"atividade_{col}"] = {
            "dates": dates_iso(te.index),
            "actual": [float(v) if np.isfinite(v) else None for v in te.to_numpy()],
            "naive": [float(v) for v in hat],
        }

    for col, lab in [
        ("diesel_mbpd", "diesel mbpd"),
        ("gasoline_mbpd", "gasolina mbpd"),
        ("rtm_sales_revenue_rsmn", "receita RT&M"),
        ("rtm_gross_profit_rsmn", "lucro bruto RT&M"),
        ("rtm_gross_margin_pct", "margem RT&M"),
    ]:
        tr, te = frames["comp_train"][col].dropna(), frames["comp_test"][col]
        hat = np.full(len(te), float(tr.iloc[-1]))
        rows.append(
            row(
                "companhia",
                lab,
                "naive",
                "2Q26",
                te,
                hat,
                extra={"note": "subvenção ITR nota 4 no 2T26"},
            )
        )
        fc[f"companhia_{col}"] = {
            "dates": dates_iso(te.index),
            "actual": [float(v) if np.isfinite(v) else None for v in te.to_numpy()],
            "naive": [float(v) for v in hat],
        }
    return rows, fc


# ---------------------------------------------------------------------------
# LSTM (PyTorch, daily PETR4)
# ---------------------------------------------------------------------------

def torch_device_str():
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _windows_yx(y: np.ndarray, x: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Window of lagged y plus contemporaneous prod (last x is prod at the target date)."""
    xs, ys = [], []
    for i in range(window, len(y)):
        y_hist = y[i - window : i]
        x_hist = x[i - window + 1 : i + 1]
        xs.append(np.stack([y_hist, x_hist], axis=1))
        ys.append(y[i])
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32)[:, None]


def run_lstm(frames: dict, notes: list[str]) -> tuple[list[dict], dict, dict]:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    torch.set_num_threads(1)
    device_s = torch_device_str()
    device = torch.device(device_s)
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    ytr = frames["mkt_train"]["petr4"].astype(float)
    yte = frames["mkt_test"]["petr4"].astype(float)
    xtr = frames["mkt_train"]["prod"].reindex(ytr.index).ffill().bfill().astype(float)
    xte = frames["mkt_test"]["prod"].reindex(yte.index).ffill().bfill().astype(float)

    def bounds(s: pd.Series) -> tuple[float, float, float]:
        lo, hi = float(s.min()), float(s.max())
        span = hi - lo if hi > lo else 1.0
        return lo, hi, span

    y_lo, y_hi, y_span = bounds(ytr)
    x_lo, x_hi, x_span = bounds(xtr)

    def sc(a, lo, span):
        return (np.asarray(a, dtype=np.float32) - lo) / span

    def unsc(a):
        return np.asarray(a, dtype=float) * y_span + y_lo

    y_s = sc(ytr.to_numpy(), y_lo, y_span)
    x_s = sc(xtr.to_numpy(), x_lo, x_span)
    x_te_s = sc(xte.to_numpy(), x_lo, x_span)
    val_n = 21
    fit_y, val_y = y_s[:-val_n], y_s[-val_n:]
    fit_x, val_x = x_s[:-val_n], x_s[-val_n:]

    class ProdLSTM(nn.Module):
        def __init__(self, hidden: int = 32):
            super().__init__()
            self.lstm = nn.LSTM(2, hidden, batch_first=True)
            self.fc = nn.Linear(hidden, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.fc(out[:, -1, :])

    def train_one(window: int, epochs: int, lr: float, y_arr: np.ndarray, x_arr: np.ndarray) -> ProdLSTM:
        X, y = _windows_yx(y_arr, x_arr, window)
        ds = TensorDataset(torch.from_numpy(X), torch.from_numpy(y))
        loader = DataLoader(ds, batch_size=64, shuffle=True)
        model = ProdLSTM(32).to(device)
        opt = torch.optim.Adam(model.parameters(), lr=lr)
        loss_fn = nn.MSELoss()
        model.train()
        for _ in range(epochs):
            for xb, yb in loader:
                xb, yb = xb.to(device), yb.to(device)
                opt.zero_grad()
                pred = model(xb)
                loss = loss_fn(pred, yb)
                loss.backward()
                opt.step()
        return model

    def roll(
        model: ProdLSTM,
        y_context: np.ndarray,
        x_all: np.ndarray,
        window: int,
        start: int,
        steps: int,
    ) -> np.ndarray:
        model.eval()
        hist = list(y_context[-window:].astype(np.float32))
        out = []
        with torch.no_grad():
            for k in range(steps):
                i = start + k
                y_slice = np.asarray(hist[-window:], dtype=np.float32)
                x_slice = x_all[i - window + 1 : i + 1].astype(np.float32)
                inp = np.stack([y_slice, x_slice], axis=1)[None, :, :]
                xt = torch.from_numpy(inp).to(device)
                yhat = float(model(xt).cpu().numpy().ravel()[0])
                out.append(yhat)
                hist.append(yhat)
        return np.asarray(out, dtype=float)

    grid = []
    for window in (21, 63):
        model = train_one(window, epochs=40, lr=1e-3, y_arr=fit_y, x_arr=fit_x)
        x_fit_val = np.concatenate([fit_x, val_x])
        hat_val = roll(model, fit_y, x_fit_val, window, start=len(fit_y), steps=len(val_y))
        rmse = float(np.sqrt(np.mean((val_y - hat_val) ** 2)))
        grid.append({"window": window, "lr": 1e-3, "epochs": 40, "hidden": 32, "val_rmse_scaled": rmse})
        print(f"  LSTM window={window} val_rmse_scaled={rmse:.4f}")

    winner = min(grid, key=lambda g: g["val_rmse_scaled"])
    window = int(winner["window"])
    print(f"  LSTM winner window={window} exog=prod")
    final = train_one(window, epochs=40, lr=1e-3, y_arr=y_s, x_arr=x_s)
    x_all = np.concatenate([x_s, x_te_s])
    hat_s = roll(final, y_s, x_all, window, start=len(y_s), steps=len(yte))
    hat = unsc(hat_s)

    rows = [
        row("mercado", "PETR4", "lstm", "5d", yte.iloc[:5], hat[:5], extra={"window": window}),
        row("mercado", "PETR4", "lstm", "21d", yte, hat, extra={"window": window}),
    ]
    fc = {
        "mercado_PETR4": {
            "dates": dates_iso(yte.index),
            "actual": [float(v) for v in yte.to_numpy()],
            "lstm": [float(v) for v in hat],
        }
    }
    info = {
        "device": device_s,
        "torch": torch.__version__,
        "exog": "prod",
        "scale_y_min": y_lo,
        "scale_y_max": y_hi,
        "scale_x_min": x_lo,
        "scale_x_max": x_hi,
        "grid": grid,
        "winner": winner,
    }
    notes.append(
        f"LSTM PETR4+prod device={device_s} window={window} val_rmse_scaled={winner['val_rmse_scaled']:.4f}"
    )
    return rows, fc, info


# ---------------------------------------------------------------------------
# SARIMAX
# ---------------------------------------------------------------------------

def _silence_statsmodels() -> None:
    logging.getLogger("pmdarima").setLevel(logging.ERROR)
    logging.getLogger("statsmodels").setLevel(logging.ERROR)
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


def _auto_arima_forecast(
    y_train,
    exog_train,
    exog_test,
    seasonal: bool,
    m: int,
    max_p=3,
    max_q=3,
    d=None,
    n_periods=1,
):
    from pmdarima import auto_arima

    kwargs = dict(
        y=np.asarray(y_train, dtype=float),
        X=None if exog_train is None else np.asarray(exog_train, dtype=float),
        seasonal=seasonal,
        stepwise=True,
        suppress_warnings=True,
        error_action="ignore",
        start_p=0,
        start_q=0,
        max_p=max_p,
        max_q=max_q,
        max_d=1,
        n_jobs=1,
        trace=False,
        maxiter=100,
    )
    if d is not None:
        kwargs["d"] = d
    if seasonal:
        kwargs.update(m=m, start_P=0, start_Q=0, max_P=1, max_Q=1, max_D=1)
    _silence_statsmodels()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = auto_arima(**kwargs)
        n = n_periods
        if exog_test is not None:
            n = len(exog_test)
        n = max(int(n), 1)
        Xf = None if exog_test is None else np.asarray(exog_test, dtype=float)
        fc = model.predict(n_periods=n, X=Xf)
    order = model.order
    sorder = model.seasonal_order if seasonal else None
    return np.asarray(fc, dtype=float), order, sorder, float(model.aic())


def run_sarimax(frames: dict, notes: list[str]) -> tuple[list[dict], dict, dict]:
    rows: list[dict] = []
    fc: dict = {}
    orders: dict = {}

    def fit_one(vector, target, y_tr, y_te, ex_tr, ex_te, short, long, seasonal, m, max_p=3, max_q=3):
        y_tr = y_tr.astype(float).dropna()
        aligned = pd.concat([y_tr, ex_tr], axis=1, sort=False).dropna()
        y_fit = aligned.iloc[:, 0]
        x_fit = aligned.iloc[:, 1:]
        x_te = ex_te.reindex(y_te.index)
        x_te = x_te.ffill().bfill()
        try:
            hat, order, sorder, aic = _auto_arima_forecast(
                y_fit, x_fit, x_te, seasonal=seasonal, m=m, max_p=max_p, max_q=max_q
            )
        except Exception as exc:
            notes.append(f"SARIMAX {target} falhou: {exc}")
            print(f"  SARIMAX {target} falhou: {exc}")
            return
        n = min(len(hat), len(y_te))
        hat, y_te = hat[:n], y_te.iloc[:n]
        extra = {"order": list(order), "seasonal_order": list(sorder) if sorder else None, "aic": aic}
        orders[f"{vector}:{target}"] = extra
        rows.append(row(vector, target, "sarimax", short, y_te.iloc[: _h(short)], hat[: _h(short)], extra=extra))
        rows.append(row(vector, target, "sarimax", long, y_te, hat, extra=extra))
        key = _fc_key(vector, target)
        fc.setdefault(key, {"dates": dates_iso(y_te.index), "actual": [float(v) for v in y_te.to_numpy()]})
        fc[key]["sarimax"] = [float(v) for v in hat]
        print(f"  SARIMAX {target} order={order} seasonal={sorder} aic={aic:.1f}")

    ytr, yte = frames["mkt_train"]["petr4"], frames["mkt_test"]["petr4"]
    fit_one(
        "mercado",
        "PETR4",
        ytr,
        yte,
        frames["mkt_train"][["prod"]],
        frames["mkt_test"][["prod"]],
        "5d",
        "21d",
        seasonal=False,
        m=1,
        max_p=3,
        max_q=3,
    )

    for col, lab in [
        ("anp_gas", "ANP gasolina"),
        ("anp_die", "ANP diesel"),
        ("pbr_gas", "Petrobras gasolina"),
        ("pbr_die", "Petrobras diesel"),
    ]:
        fit_one(
            "preço",
            lab,
            frames["price_train"][col],
            frames["price_test"][col],
            frames["price_train"][["prod"]],
            frames["price_test"][["prod"]],
            "4w",
            "8w",
            seasonal=True,
            m=52,
            max_p=2,
            max_q=2,
        )

    for col, lab in [
        ("abcr_heavy", "tráfego pesado"),
        ("pim", "indústria"),
        ("pmc", "varejo"),
        ("unemp", "desemprego"),
    ]:
        fit_one(
            "atividade",
            lab,
            frames["act_train"][col],
            frames["act_test"][col],
            frames["act_train"][["prod"]],
            frames["act_test"][["prod"]],
            "1m",
            "3m",
            seasonal=True,
            m=12,
            max_p=2,
            max_q=2,
        )

    r2, f2, o2 = run_sarimax_company(frames, notes)
    rows.extend(r2)
    _merge_fc(fc, f2)
    orders.update(o2)
    return rows, fc, orders


def _sarimax_exog_forecast(y_train, exog_train, exog_test, d=1, max_p=2, max_q=2):
    """Small (p,d,q) grid with statsmodels. Used on the quarterly panel so
    the company vector does not need pmdarima (absent on this Windows)."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    y = np.asarray(y_train, dtype=float)
    X = None if exog_train is None else np.asarray(exog_train, dtype=float)
    Xf = None if exog_test is None else np.asarray(exog_test, dtype=float)
    best = None
    best_aic = math.inf
    best_order = None
    _silence_statsmodels()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for p in range(max_p + 1):
            for q in range(max_q + 1):
                try:
                    mod = SARIMAX(
                        y,
                        order=(p, d, q),
                        exog=X,
                        trend=None,
                        enforce_stationarity=False,
                        enforce_invertibility=False,
                    )
                    res = mod.fit(disp=False, maxiter=200)
                    if np.isfinite(res.aic) and res.aic < best_aic:
                        best_aic = float(res.aic)
                        best = res
                        best_order = (p, d, q)
                except Exception:
                    continue
    if best is None:
        raise RuntimeError("SARIMAX company grid produced no fit")
    n = 1 if Xf is None else len(Xf)
    fc = best.forecast(steps=n, exog=Xf)
    return np.asarray(fc, dtype=float), best_order, None, float(best.aic)


def run_sarimax_company(frames: dict, notes: list[str]) -> tuple[list[dict], dict, dict]:
    """One-step SARIMAX on the five 2Q26 company targets.

    Exogenous series is prod_pbr: daily PPI × same-quarter Petrobras mbpd,
    summed on that quarter. No lag. 1Q25 X is Jan–Mar 2025; 2Q26 X is
    Apr–Jun 2026. Force d=1 so the grid does not pick (0,0,0).
    """
    rows: list[dict] = []
    fc: dict = {}
    orders: dict = {}
    x_tr = frames["comp_train"]["prod_pbr"]
    x_te = frames["comp_test"]["prod_pbr"]
    for col, lab in [
        ("diesel_mbpd", "diesel mbpd"),
        ("gasoline_mbpd", "gasolina mbpd"),
        ("rtm_sales_revenue_rsmn", "receita RT&M"),
        ("rtm_gross_profit_rsmn", "lucro bruto RT&M"),
        ("rtm_gross_margin_pct", "margem RT&M"),
    ]:
        y_tr = frames["comp_train"][col].astype(float).dropna()
        y_te = frames["comp_test"][col]
        aligned = pd.concat([y_tr, x_tr], axis=1, sort=False).dropna()
        y_fit = aligned.iloc[:, 0]
        x_fit = aligned.iloc[:, [1]]
        x_te_one = x_te.reindex(y_te.index).to_frame()
        x_te_one.columns = x_fit.columns
        x_te_one = x_te_one.ffill().bfill()
        try:
            hat, order, sorder, aic = _sarimax_exog_forecast(
                y_fit,
                x_fit,
                x_te_one,
                d=1,
                max_p=2,
                max_q=2,
            )
        except Exception as exc:
            notes.append(f"SARIMAX companhia {lab} falhou: {exc}")
            print(f"  SARIMAX {lab} falhou: {exc}")
            continue
        extra = {
            "order": list(order),
            "seasonal_order": list(sorder) if sorder else None,
            "aic": aic,
            "note": "prod_pbr contemporâneo (PPI × volume do próprio trimestre); d=1; subvenção ITR nota 4 no 2T26",
        }
        orders[f"companhia:{lab}"] = extra
        rows.append(row("companhia", lab, "sarimax", "2Q26", y_te, hat[: len(y_te)], extra=extra))
        key = f"companhia_{col}"
        fc.setdefault(key, {"dates": dates_iso(y_te.index), "actual": [float(v) for v in y_te.to_numpy()]})
        fc[key]["sarimax"] = [float(v) for v in hat[: len(y_te)]]
        print(
            f"  SARIMAX {lab} order={order} aic={aic:.1f} "
            f"hat={hat[0]:.4g} actual={float(y_te.iloc[0]):.4g}"
        )
    return rows, fc, orders


def _h(horizon: str) -> int:
    return {"5d": 5, "21d": 21, "4w": 4, "8w": 8, "1m": 1, "3m": 3, "2Q26": 1}[horizon]


def _fc_key(vector: str, target: str) -> str:
    mapping = {
        ("mercado", "PETR4"): "mercado_PETR4",
        ("preço", "ANP gasolina"): "preco_anp_gas",
        ("preço", "ANP diesel"): "preco_anp_die",
        ("preço", "Petrobras gasolina"): "preco_pbr_gas",
        ("preço", "Petrobras diesel"): "preco_pbr_die",
        ("atividade", "tráfego pesado"): "atividade_abcr_heavy",
        ("atividade", "indústria"): "atividade_pim",
        ("atividade", "varejo"): "atividade_pmc",
        ("atividade", "desemprego"): "atividade_unemp",
    }
    return mapping.get((vector, target), f"{vector}_{target}")


# ---------------------------------------------------------------------------
# Prophet
# ---------------------------------------------------------------------------

def _prophet_forecast(y: pd.Series, exog: pd.Series, future_index: pd.Index, future_exog: pd.Series) -> np.ndarray:
    from prophet import Prophet

    df = pd.DataFrame({"ds": y.index, "y": y.to_numpy(dtype=float), "exog": exog.to_numpy(dtype=float)}).dropna()
    m = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
    m.add_regressor("exog")
    logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
    logging.getLogger("prophet").setLevel(logging.ERROR)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.fit(df)
        future = pd.DataFrame({"ds": future_index})
        future["exog"] = future_exog.reindex(future_index).ffill().bfill().to_numpy(dtype=float)
        pred = m.predict(future)
    return pred["yhat"].to_numpy(dtype=float)


def run_prophet(frames: dict, notes: list[str]) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    fc: dict = {}

    def one(vector, target, y_tr, y_te, ex_tr, ex_te, short, long, key):
        y_tr = y_tr.astype(float)
        ex_tr = ex_tr.astype(float)
        aligned = pd.concat([y_tr, ex_tr], axis=1, sort=False).dropna()
        aligned.columns = ["y", "exog"]
        future_exog = ex_te.astype(float).reindex(y_te.index).ffill().bfill()
        try:
            hat = _prophet_forecast(aligned["y"], aligned["exog"], y_te.index, future_exog)
        except Exception as exc:
            notes.append(f"Prophet {target} falhou: {exc}")
            print(f"  Prophet {target} falhou: {exc}")
            return
        n = min(len(hat), len(y_te))
        hat, y_te = hat[:n], y_te.iloc[:n]
        rows.append(row(vector, target, "prophet", short, y_te.iloc[: _h(short)], hat[: _h(short)]))
        rows.append(row(vector, target, "prophet", long, y_te, hat))
        fc.setdefault(key, {"dates": dates_iso(y_te.index), "actual": [float(v) for v in y_te.to_numpy()]})
        fc[key]["prophet"] = [float(v) for v in hat]
        print(f"  Prophet {target} n_test={n}")

    for col, lab in [
        ("anp_gas", "ANP gasolina"),
        ("anp_die", "ANP diesel"),
        ("pbr_gas", "Petrobras gasolina"),
        ("pbr_die", "Petrobras diesel"),
    ]:
        one(
            "preço",
            lab,
            frames["price_train"][col],
            frames["price_test"][col],
            frames["price_train"]["prod"],
            frames["price_test"]["prod"],
            "4w",
            "8w",
            f"preco_{col}",
        )

    for col, lab in [
        ("abcr_heavy", "tráfego pesado"),
        ("pim", "indústria"),
        ("pmc", "varejo"),
        ("unemp", "desemprego"),
    ]:
        one(
            "atividade",
            lab,
            frames["act_train"][col],
            frames["act_test"][col],
            frames["act_train"]["prod"],
            frames["act_test"]["prod"],
            "1m",
            "3m",
            f"atividade_{col}",
        )
    return rows, fc


# ---------------------------------------------------------------------------
# TimesFM 3.0
# ---------------------------------------------------------------------------

def _timesfm_forecaster(device_s: str):
    if sys.platform == "darwin":
        try:
            from timesfm3.mlx import TimesFM3Forecaster

            print("  TimesFM backend=MLX")
            return TimesFM3Forecaster.from_pretrained(CHECKPOINT), "mlx"
        except Exception as exc:
            print(f"  TimesFM MLX indisponível ({exc}); tenta PyTorch")
    from timesfm3 import TimesFM3Evaluator, ModelConfig

    cfg = ModelConfig(checkpoint_path=CHECKPOINT, per_core_batch_size=8, device=device_s)
    return TimesFM3Evaluator(cfg), "pytorch"


def _timesfm_point(out) -> np.ndarray:
    fc = np.asarray(out.forecast, dtype=float)
    if fc.ndim == 2:
        fc = fc[0]
    return fc.ravel()


def run_timesfm(frames: dict, notes: list[str]) -> tuple[list[dict], dict, dict]:
    ytr = frames["mkt_train"]["petr4"].astype(float).dropna()
    yte = frames["mkt_test"]["petr4"].astype(float)
    prod_tr = frames["mkt_train"]["prod"].reindex(ytr.index).ffill().bfill()
    ctx = ytr.to_numpy(dtype=np.float32)
    cov = prod_tr.to_numpy(dtype=np.float32)[None, :]
    h = len(yte)
    info: dict = {}
    rows: list[dict] = []
    fc: dict = {}

    try:
        device_s = torch_device_str()
    except Exception:
        device_s = "cpu"
    try:
        forecaster, backend = _timesfm_forecaster(device_s)
    except Exception as exc:
        notes.append(f"TimesFM não carregou: {exc}")
        print(f"  TimesFM não carregou: {exc}")
        traceback.print_exc()
        return rows, fc, {"error": str(exc)}

    info["backend"] = backend
    info["device"] = device_s
    info["checkpoint"] = CHECKPOINT
    info["exog"] = "prod"
    info["covariate_note"] = "past_only_covariates=prod on train; TimesFM 3.0 has no horizon regressor"

    def predict_cov():
        kwargs = dict(horizon=h, past_only_covariates=cov, return_quantiles=False)
        if hasattr(forecaster, "predict"):
            try:
                return forecaster.predict(ctx, **kwargs)
            except TypeError:
                return forecaster.predict(ctx, horizon=h, past_only_covariates=cov)
        outs = list(
            forecaster.predict_batch(
                [ctx], horizon=h, past_only_covariates=[cov], return_quantiles=False
            )
        )
        return outs[0]

    try:
        hat_cov = _timesfm_point(predict_cov())[:h]
        rows.append(row("mercado", "PETR4", "timesfm_cov", "5d", yte.iloc[:5], hat_cov[:5]))
        rows.append(row("mercado", "PETR4", "timesfm_cov", "21d", yte, hat_cov))
        fc.setdefault(
            "mercado_PETR4",
            {"dates": dates_iso(yte.index), "actual": [float(v) for v in yte.to_numpy()]},
        )
        fc["mercado_PETR4"]["timesfm_cov"] = [float(v) for v in hat_cov]
        print(f"  TimesFM prod horizonte={h}")
    except Exception as exc:
        notes.append(f"TimesFM com prod falhou: {exc}")
        print(f"  TimesFM com prod falhou: {exc}")
        traceback.print_exc()

    return rows, fc, info


# ---------------------------------------------------------------------------
# Figures from stored forecasts
# ---------------------------------------------------------------------------

def write_eda_figures(root: Path, frames: dict) -> list[str]:
    """Redraw EDA line charts from the frozen snapshot (no matplotlib)."""
    eda_dir = figures_eda_dir(root)
    eda_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    daily = frames["daily"]
    monthly = frames["monthly"]
    price = frames["price_week"]
    fin = frames["fin"]

    jobs = [
        (
            "eda_mercado_petr4.svg",
            "Fechamento de PETR4",
            "R$",
            daily.index,
            {"PETR4": daily["petr4"].to_numpy()},
        ),
        (
            "eda_ppi_desvio.svg",
            "Desvio PPI em R$/L",
            "R$/L",
            daily.index,
            {"gasolina": daily["pbr_gas_R"].to_numpy(), "diesel": daily["pbr_die_R"].to_numpy()},
        ),
        (
            "eda_indicador_prod.svg",
            "Produto diário desvio × volume",
            "R$",
            daily.index,
            {"prod": daily["prod"].to_numpy()},
        ),
        (
            "eda_indicador_stock.svg",
            "Estoque acumulado",
            "R$",
            daily.index,
            {"stock": daily["stock"].to_numpy()},
        ),
        (
            "eda_preco.svg",
            "Preço semanal ANP e Petrobras",
            "R$/L",
            price.index,
            {
                "ANP gasolina": price["anp_gas"].to_numpy(),
                "ANP diesel": price["anp_die"].to_numpy(),
                "Petrobras gasolina": price["pbr_gas"].to_numpy(),
                "Petrobras diesel": price["pbr_die"].to_numpy(),
            },
        ),
        (
            "eda_atividade_heavy.svg",
            "Tráfego pesado ABCR",
            "índice",
            monthly.index,
            {"ABCR pesado": monthly["abcr_heavy"].to_numpy()},
        ),
        (
            "eda_atividade_pim.svg",
            "Indústria PIM-PF",
            "índice",
            monthly.index,
            {"PIM-PF": monthly["pim"].to_numpy()},
        ),
        (
            "eda_atividade_pmc.svg",
            "Varejo PMC",
            "índice",
            monthly.index,
            {"PMC": monthly["pmc"].to_numpy()},
        ),
        (
            "eda_atividade_unemp.svg",
            "Desemprego PNAD",
            "%",
            monthly.index,
            {"desemprego": monthly["unemp"].to_numpy()},
        ),
        (
            "eda_companhia_margem.svg",
            "Margem bruta RT&M",
            "%",
            fin.index,
            {"margem": fin["rtm_gross_margin_pct"].to_numpy()},
        ),
        (
            "eda_companhia_receita.svg",
            "Receita RT&M",
            "R$ milhões",
            fin.index,
            {"receita": fin["rtm_sales_revenue_rsmn"].to_numpy()},
        ),
        (
            "eda_companhia_lucro.svg",
            "Lucro bruto RT&M",
            "R$ milhões",
            fin.index,
            {"lucro bruto": fin["rtm_gross_profit_rsmn"].to_numpy()},
        ),
        (
            "eda_companhia_volume.svg",
            "Volume Petrobras",
            "mbpd",
            fin.index,
            {
                "diesel": fin["diesel_mbpd"].to_numpy(),
                "gasolina": fin["gasoline_mbpd"].to_numpy(),
            },
        ),
    ]
    for fname, title, ylabel, idx, series in jobs:
        write_overlay_svg(eda_dir / fname, title, ylabel, idx, series)
        written.append(fname)
        print(f"  EDA {fname}")
    return written


def write_figures(root: Path, frames: dict, forecasts: dict) -> list[str]:
    fc_dir = figures_forecasts_dir(root)
    fc_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    store: dict = {}
    fp = forecasts_path(root)
    if fp.exists():
        store = json.loads(fp.read_text(encoding="utf-8"))
    _merge_fc(store, forecasts)

    def pack(key: str, title: str, ylabel: str, fname: str, idx, actual):
        blob = store.get(key, {})
        series = {"real": np.asarray(blob.get("actual", actual), dtype=float)}
        for name in ("naive", "lstm", "sarimax", "prophet", "timesfm_cov"):
            if name in blob:
                series[name] = np.asarray(blob[name], dtype=float)
        if len(series) < 2:
            return
        write_overlay_svg(fc_dir / fname, title, ylabel, idx, series)
        written.append(fname)

    pack(
        "mercado_PETR4",
        "PETR4 no teste (21 pregões)",
        "R$",
        "fc_mercado_petr4.svg",
        frames["mkt_test"].index,
        frames["mkt_test"]["petr4"].to_numpy(),
    )
    for col, lab in [
        ("anp_gas", "ANP gasolina"),
        ("anp_die", "ANP diesel"),
        ("pbr_gas", "Petrobras gasolina"),
        ("pbr_die", "Petrobras diesel"),
    ]:
        pack(
            f"preco_{col}",
            f"{lab} no teste (8 semanas)",
            "R$/L",
            f"fc_preco_{col}.svg",
            frames["price_test"].index,
            frames["price_test"][col].to_numpy(),
        )
    FAN_COLORS = {
        "real": "#000000",
        "naive": "#1f77b4",
        "sarimax": "#d62728",
        "prophet": "#2ca02c",
    }
    for col, lab, ylabel in [
        ("abcr_heavy", "tráfego pesado", "índice"),
        ("pim", "indústria", "índice"),
        ("pmc", "varejo", "índice"),
        ("unemp", "desemprego", "p.p."),
    ]:
        blob = store.get(f"atividade_{col}", {})
        idx, series, origin_i = series_history_and_fan(
            frames["act_train"][col],
            frames["act_test"][col],
            blob,
            ("naive", "sarimax", "prophet"),
        )
        write_overlay_svg(
            fc_dir / f"fc_atividade_{col}.svg",
            f"{lab}: série vista e previsão (mai.–jul. 2026)",
            ylabel,
            idx,
            series,
            colors=FAN_COLORS,
            origin_i=origin_i,
            mark_all={"real"},
        )
        written.append(f"fc_atividade_{col}.svg")
    for col, lab, ylabel in [
        ("diesel_mbpd", "diesel mbpd", "mbpd"),
        ("gasoline_mbpd", "gasolina mbpd", "mbpd"),
        ("rtm_sales_revenue_rsmn", "receita RT&M", "R$ milhões"),
        ("rtm_gross_profit_rsmn", "lucro bruto RT&M", "R$ milhões"),
        ("rtm_gross_margin_pct", "margem RT&M", "%"),
    ]:
        blob = store.get(f"companhia_{col}", {})
        idx, series, origin_i = series_history_and_fan(
            frames["comp_train"][col],
            frames["comp_test"][col],
            blob,
            ("naive", "sarimax"),
        )
        write_overlay_svg(
            fc_dir / f"fc_companhia_{col}.svg",
            f"{lab}: série vista e previsão (2T26)",
            ylabel,
            idx,
            series,
            colors=FAN_COLORS,
            origin_i=origin_i,
            mark_all={"real"},
        )
        written.append(f"fc_companhia_{col}.svg")
    return written


def metrics_table(payload: dict) -> pd.DataFrame:
    df = pd.DataFrame(payload.get("rows", []))
    if df.empty:
        return df
    cols = [c for c in ["vector", "target", "model", "horizon", "MAE", "MSE", "RMSE", "order", "window", "note"] if c in df.columns]
    return df[cols].sort_values(["vector", "target", "model", "horizon"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def default_families() -> tuple[str, ...]:
    if sys.platform == "win32":
        return WIN_DEFAULT
    return FULL_DEFAULT


def run_etapa3(
    project_root: Path | None = None,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    force: bool = False,
) -> dict:
    root = Path(project_root) if project_root is not None else find_project_root()
    ensure_output_dirs(root)
    families = list(only) if only else list(default_families())
    skip_set = set(skip or [])
    families = [f for f in families if f not in skip_set]

    print(f"root={root}")
    print(f"platform={sys.platform}  families={families}")
    frames = load_frames(root)
    print(
        "cortes:",
        "mkt",
        len(frames["mkt_train"]),
        len(frames["mkt_test"]),
        "preço",
        len(frames["price_train"]),
        len(frames["price_test"]),
        "atividade",
        len(frames["act_train"]),
        len(frames["act_test"]),
        "companhia",
        len(frames["comp_train"]),
        len(frames["comp_test"]),
    )

    payload = load_payload(root)
    payload.setdefault("rows", [])
    payload.setdefault("notes", [])
    payload.setdefault("meta", {})
    payload["meta"].update(
        {
            "platform": sys.platform,
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "families_this_run": families,
        }
    )
    notes = list(payload.get("notes", []))
    new_rows: list[dict] = []
    forecasts: dict = {}

    def has_model(name: str) -> bool:
        return any(r.get("model") == name for r in payload.get("rows", []))

    if "naive" in families and (force or not has_model("naive")):
        print("== naive")
        r, f = run_naive(frames)
        new_rows.extend(r)
        _merge_fc(forecasts, f)
    elif "naive" in families:
        print("== naive (já no JSON)")

    if "lstm" in families and (force or not has_model("lstm")):
        print("== lstm")
        try:
            r, f, info = run_lstm(frames, notes)
            new_rows.extend(r)
            _merge_fc(forecasts, f)
            payload["lstm"] = info
        except Exception as exc:
            notes.append(f"LSTM falhou: {exc}")
            print(f"LSTM falhou: {exc}")
            traceback.print_exc()
    elif "lstm" in families:
        print("== lstm (já no JSON)")

    if "sarimax" in families:
        if sys.platform == "win32":
            notes.append("SARIMAX ignorado neste Windows (OpenBLAS).")
            print("== sarimax ignorado (win32)")
        else:
            print("== sarimax")
            r, f, orders = run_sarimax(frames, notes)
            new_rows.extend(r)
            _merge_fc(forecasts, f)
            payload.setdefault("sarimax_orders", {}).update(orders)

    if "company" in families and "sarimax" not in families:
        # Short quarterly panel (~16 points). Try even on Windows.
        print("== company")
        r, f, orders = run_sarimax_company(frames, notes)
        new_rows.extend(r)
        _merge_fc(forecasts, f)
        payload.setdefault("sarimax_orders", {}).update(orders)

    if "prophet" in families:
        if sys.platform == "win32":
            notes.append("Prophet ignorado neste Windows (OpenBLAS).")
            print("== prophet ignorado (win32)")
        else:
            print("== prophet")
            r, f = run_prophet(frames, notes)
            new_rows.extend(r)
            _merge_fc(forecasts, f)

    if "timesfm" in families:
        if sys.platform == "win32":
            notes.append("TimesFM 3.0 ignorado neste Windows; roda no M4.")
            print("== timesfm ignorado (win32)")
        else:
            print("== timesfm")
            r, f, info = run_timesfm(frames, notes)
            new_rows.extend(r)
            _merge_fc(forecasts, f)
            payload["timesfm"] = info

    # unique notes, keep order; drop stale company failures after a successful fit
    if any(r.get("vector") == "companhia" and r.get("model") == "sarimax" for r in new_rows):
        notes = [n for n in notes if "SARIMAX companhia" not in n or "falhou" not in n]
    seen = set()
    payload["notes"] = [n for n in notes if not (n in seen or seen.add(n))]
    payload["rows"] = merge_rows(payload.get("rows", []), new_rows)
    save_payload(root, payload, forecasts)
    written = write_figures(root, frames, forecasts)
    payload["figures"] = written
    save_payload(root, payload, forecasts)
    table = metrics_table(payload)
    print(table.to_string(index=False) if not table.empty else "(sem linhas)")
    print("métricas:", metrics_path(root))
    return {"payload": payload, "table": table, "frames": frames, "root": root}


def _merge_fc(dst: dict, src: dict) -> None:
    for k, v in src.items():
        dst.setdefault(k, {})
        dst[k].update(v)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Etapa 3 forecast runner")
    p.add_argument("--only", default="", help="comma list: naive,lstm,sarimax,company,prophet,timesfm")
    p.add_argument("--skip", default="", help="comma list to skip")
    p.add_argument("--force", action="store_true", help="refit even if JSON already has the model")
    p.add_argument("--eda", action="store_true", help="redraw EDA SVG charts from the snapshot and exit")
    p.add_argument(
        "--figures",
        action="store_true",
        help="redraw forecast overlay SVGs from JSON and exit",
    )
    args = p.parse_args(argv)
    if args.eda:
        root = find_project_root()
        frames = load_frames(root)
        written = write_eda_figures(root, frames)
        print("EDA figures:", ", ".join(written))
        return 0
    if args.figures:
        root = find_project_root()
        frames = load_frames(root)
        written = write_figures(root, frames, {})
        print("forecast figures:", ", ".join(written))
        return 0
    only = [s.strip() for s in args.only.split(",") if s.strip()] or None
    skip = [s.strip() for s in args.skip.split(",") if s.strip()] or None
    run_etapa3(only=only, skip=skip, force=args.force)
    return 0


if __name__ == "__main__":
    src_dir = Path(__file__).resolve().parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    raise SystemExit(main())
