# -*- coding: utf-8 -*-
"""PETR4 vs BOVA11: daily PPI lags and quarterly accumulation (Etapa 4).

Rebuilds from local SQLite files. Collection lives behind --export-supplement.
Does not change official notebooks, etapa4_run.py, or the course freeze.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sqlite3
import sys
import warnings
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.gridspec import GridSpec

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import etapa3_models as e3
from db_access import find_project_root
from etapa4_charts import (
    COLOR_CTRL,
    COLOR_CORR,
    COLOR_OBS,
    COLOR_PBR,
    COLOR_PPI,
    COLOR_ZERO,
    _fonte,
    _style,
    _wrapped_note,
    figures_dir,
    save_figure,
    save_table,
)
from etapa4_data import CURRENT_FREEZE, CURRENT_SHA256, engine_for, sqlite_file
from etapa4_prod_contrib import (
    ALPHAS,
    _score,
    eval_named_groups,
    fit_ridge,
    pick_alpha,
    roll_ridge,
    summarize,
)
from paths import data_dir, results_dir

warnings.filterwarnings("ignore")

WINDOW_START = date(2022, 2, 1)
WINDOW_END = date(2026, 9, 18)
OVERLAY_FILE = "etapa4_equity_overlay_2023-11-17.json"
MN = 1_000_000.0
# ANBIMA national holidays (Dado cache holidays_b3.json, years 2022-2026).
# B3 year-end closures are applied separately in b3_session_index.
ANBIMA_HOLIDAYS = frozenset({
    date(2022, 1, 1), date(2022, 2, 28), date(2022, 3, 1), date(2022, 4, 15),
    date(2022, 4, 21), date(2022, 5, 1), date(2022, 6, 16), date(2022, 9, 7),
    date(2022, 10, 12), date(2022, 11, 2), date(2022, 11, 15), date(2022, 12, 25),
    date(2023, 1, 1), date(2023, 2, 20), date(2023, 2, 21), date(2023, 4, 7),
    date(2023, 4, 21), date(2023, 5, 1), date(2023, 6, 8), date(2023, 9, 7),
    date(2023, 10, 12), date(2023, 11, 2), date(2023, 11, 15), date(2023, 12, 25),
    date(2024, 1, 1), date(2024, 2, 12), date(2024, 2, 13), date(2024, 3, 29),
    date(2024, 4, 21), date(2024, 5, 1), date(2024, 5, 30), date(2024, 9, 7),
    date(2024, 10, 12), date(2024, 11, 2), date(2024, 11, 15), date(2024, 11, 20),
    date(2024, 12, 25),
    date(2025, 1, 1), date(2025, 3, 3), date(2025, 3, 4), date(2025, 4, 18),
    date(2025, 4, 21), date(2025, 5, 1), date(2025, 6, 19), date(2025, 9, 7),
    date(2025, 10, 12), date(2025, 11, 2), date(2025, 11, 15), date(2025, 11, 20),
    date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17), date(2026, 4, 3),
    date(2026, 4, 21), date(2026, 5, 1), date(2026, 6, 4), date(2026, 9, 7),
})
DAILY_BLOCKS = (
    ("2026-02-19", "2026-03-19"),
    ("2026-03-20", "2026-04-20"),
    ("2026-04-22", "2026-05-21"),
    ("2026-05-22", "2026-06-22"),
    ("2026-06-23", "2026-07-21"),
    ("2026-07-22", "2026-08-19"),
)
A_GROUPS = {
    "a_history": [],
    "a_ppi_l1": ["ppi_gas_l1", "ppi_die_l1"],
    "a_ppi_l2": ["ppi_gas_l2", "ppi_die_l2"],
    "a_ppi_l3": ["ppi_gas_l3", "ppi_die_l3"],
    "a_ppi_l4": ["ppi_gas_l4", "ppi_die_l4"],
    "a_ppi_l5": ["ppi_gas_l5", "ppi_die_l5"],
}
B_GROUPS = {
    "b_clock": ["quarter_session", "quarter_session_sq"],
    "b_clock_prod": ["quarter_session", "quarter_session_sq", "C_total_qtd"],
    "b_history_clock": ["quarter_session", "quarter_session_sq", "y_lag1", "y_lag2"],
    "b_history_clock_prod": [
        "quarter_session", "quarter_session_sq", "y_lag1", "y_lag2", "C_total_qtd",
    ],
    "b_history_clock_fuels": [
        "quarter_session", "quarter_session_sq", "y_lag1", "y_lag2", "C_gas_qtd", "C_die_qtd",
    ],
}
B_CONTROLS = {
    "b_clock_prod": "b_clock",
    "b_history_clock": "b_clock",
    "b_history_clock_prod": "b_history_clock",
    "b_history_clock_fuels": "b_history_clock",
}
EVAL_QUARTERS = ("2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2")
EQUITY_COLS = (
    "tradedate", "ticker", "price_open", "price_max", "price_min", "price_med",
    "price_last", "offer_buy", "offer_sell", "total_transactions", "total_quantity",
    "total_cash", "vol_hist", "vol_hist_021", "vol_hist_126", "vol_hist_252",
    "source_db", "ingested_at",
)
NOTE_A = (
    "As faixas indicam os blocos de 21 pregões. O modelo é ajustado no início de cada bloco, "
    "e seus coeficientes permanecem fixos dentro dele. As estimativas de um passo usam valores "
    "anteriores observados do alvo e PPI defasado. As linhas ligam pregões consecutivos; "
    "a viabilidade ex ante não foi avaliada. Erro = observado − estimado, em pontos percentuais."
)
NOTE_B = (
    "As interrupções nas fronteiras de trimestre são resets deliberados, não lacunas de pregão. "
    "O modelo é ajustado antes de cada trimestre, com coeficientes fixos dentro dele. "
    "A exposição acumulada é contemporânea e descritiva. Erro = observado − estimado, em pontos percentuais."
)
FONTE = "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4."


class BovaError(RuntimeError):
    """Raised when audit, coverage, or matching fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _b3_year_end_closures(year: int) -> set[date]:
    """B3 year-end non-sessions. ANBIMA still marks these as business days."""
    closed = {date(year, 12, 24)}
    nye = date(year, 12, 31)
    if nye.weekday() == 5:
        closed.add(date(year, 12, 30))
    elif nye.weekday() == 6:
        closed.add(date(year, 12, 29))
    else:
        closed.add(nye)
    return closed


def b3_session_index(start: date | None = None, end: date | None = None) -> pd.DatetimeIndex:
    """Independent B3 session calendar. Do not derive it from equity series."""
    start = start or WINDOW_START
    end = end or WINDOW_END
    closed = set(ANBIMA_HOLIDAYS)
    for year in range(start.year, end.year + 1):
        closed.update(_b3_year_end_closures(year))
    days = pd.bdate_range(start, end, freq="C")
    keep = [ts for ts in days if ts.date() not in closed]
    return pd.DatetimeIndex(keep)


def overlay_path(root: Path | None = None) -> Path:
    path = data_dir(root) / OVERLAY_FILE
    if not path.exists():
        raise BovaError(f"missing overlay {path}")
    return path


def load_overlay(root: Path | None = None) -> dict:
    path = overlay_path(root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sha256"] = sha256_file(path)
    payload["path"] = path.name
    return payload


def _overlay_frame(rows: list[dict], ticker: str) -> pd.DataFrame:
    recs = [dict(r) for r in rows if r.get("ticker") == ticker]
    if not recs:
        return pd.DataFrame()
    frame = pd.DataFrame(recs)
    frame["tradedate"] = pd.to_datetime(frame["tradedate"])
    frame["ticker"] = ticker
    return frame


def apply_equity_overlay(df: pd.DataFrame, ticker: str, overlay: dict) -> pd.DataFrame:
    extra = _overlay_frame(overlay.get("rows", []), ticker)
    if extra.empty:
        return df
    keep = ~df["tradedate"].isin(extra["tradedate"])
    add = extra.reindex(columns=df.columns)
    out = pd.concat([df.loc[keep], add], ignore_index=True)
    out = out.sort_values("tradedate").reset_index(drop=True)
    if out["tradedate"].duplicated().any():
        raise BovaError(f"overlay created duplicate dates for {ticker}")
    return out


def _load_gas_env() -> None:
    root = Path("/mnt/opencode/gas_flare")
    env_path = root / ".secret" / ".env"
    if not env_path.exists():
        raise BovaError(f"missing {env_path}")
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _redact_url(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": (parsed.path or "").lstrip("/"),
        "user_present": bool(parsed.username),
        "password_present": bool(parsed.password),
    }


def manifest_path(root: Path | None = None) -> Path:
    return data_dir(root) / "etapa4_bova11_manifest.json"


def supplement_path(root: Path | None = None) -> Path:
    man = json.loads(manifest_path(root).read_text(encoding="utf-8"))
    path = data_dir(root) / man["export_file"]
    if not path.exists():
        raise BovaError(f"missing supplement {path}")
    actual = sha256_file(path)
    if actual != man["sha256"]:
        raise BovaError(f"supplement SHA-256 mismatch: {actual}")
    return path


def export_supplement(root: Path | None = None) -> Path:
    """Read BOVA11 from gasflaredb and write a local supplement. Requires DB env."""
    from sqlalchemy import create_engine, text

    root = root or find_project_root()
    _load_gas_env()
    dado = os.environ.get("DADODB_CONNECTION_STRING", "").strip()
    gas = os.environ.get("GASFLARE_CONNECTION_STRING", "").strip()
    if not dado or not gas:
        raise BovaError("database URLs missing")
    cols = ", ".join(EQUITY_COLS)
    sql = (
        f"SELECT {cols} FROM equity_daily WHERE ticker = :ticker "
        "AND tradedate BETWEEN :d0 AND :d1 ORDER BY tradedate"
    )
    params = {"ticker": "BOVA11", "d0": WINDOW_START, "d1": WINDOW_END}
    gas_eng = create_engine(gas, pool_pre_ping=True)
    dado_eng = create_engine(dado, pool_pre_ping=True)
    try:
        gas_df = pd.read_sql(text(sql), gas_eng, params=params)
        dado_df = pd.read_sql(
            text(
                "SELECT tradedate, ticker, price_last FROM public.tbl_asset "
                "WHERE ticker = :ticker AND tradedate BETWEEN :d0 AND :d1 "
                "ORDER BY tradedate"
            ),
            dado_eng,
            params=params,
        )
    finally:
        gas_eng.dispose()
        dado_eng.dispose()
    if gas_df.empty:
        raise BovaError("gasflaredb has no BOVA11 rows in the frozen window")
    gas_df["tradedate"] = pd.to_datetime(gas_df["tradedate"]).dt.date
    dado_df["tradedate"] = pd.to_datetime(dado_df["tradedate"]).dt.date
    if gas_df["tradedate"].nunique() != len(gas_df):
        raise BovaError("duplicate (ticker, tradedate) in gasflaredb BOVA11")
    merged = gas_df.merge(dado_df, on=["tradedate", "ticker"], suffixes=("_gas", "_dado"))
    if len(merged) != len(gas_df) or len(merged) != len(dado_df):
        raise BovaError(
            f"Dado/gasflaredb row mismatch: dado={len(dado_df)} gas={len(gas_df)} both={len(merged)}"
        )
    if not np.allclose(merged["price_last_gas"].astype(float), merged["price_last_dado"].astype(float)):
        raise BovaError("price_last differs between Dado and gasflaredb")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = data_dir(root) / f"etapa4_bova11_{stamp}.sqlite"
    con = sqlite3.connect(out)
    try:
        con.execute(
            """
            CREATE TABLE equity_daily (
                id INTEGER NOT NULL,
                tradedate DATE NOT NULL,
                ticker VARCHAR(35) NOT NULL,
                price_open FLOAT, price_max FLOAT, price_min FLOAT, price_med FLOAT, price_last FLOAT,
                offer_buy FLOAT, offer_sell FLOAT,
                total_transactions BIGINT, total_quantity BIGINT, total_cash FLOAT,
                vol_hist FLOAT, vol_hist_021 FLOAT, vol_hist_126 FLOAT, vol_hist_252 FLOAT,
                source_db TEXT, ingested_at DATETIME NOT NULL,
                PRIMARY KEY (id), UNIQUE (ticker, tradedate)
            )
            """
        )
        rows = []
        for i, rec in enumerate(gas_df.to_dict(orient="records"), start=1):
            rec = dict(rec)
            rec["id"] = i
            rec["tradedate"] = str(rec["tradedate"])
            rec["ticker"] = "BOVA11"
            rec["ingested_at"] = str(rec["ingested_at"])
            rows.append(tuple(rec[c] if c != "id" else i for c in ("id", *EQUITY_COLS)))
        con.executemany(
            "INSERT INTO equity_daily (id, "
            + ", ".join(EQUITY_COLS)
            + ") VALUES (" + ", ".join(["?"] * (1 + len(EQUITY_COLS))) + ")",
            rows,
        )
        con.commit()
    finally:
        con.close()
    check = pd.read_sql("SELECT tradedate, price_last FROM equity_daily ORDER BY tradedate", sqlite3.connect(out))
    check["tradedate"] = pd.to_datetime(check["tradedate"]).dt.date
    cmp_ = gas_df[["tradedate", "price_last"]].merge(check, on="tradedate", suffixes=("_src", "_out"))
    if len(cmp_) != len(gas_df) or not np.allclose(cmp_["price_last_src"].astype(float), cmp_["price_last_out"].astype(float)):
        raise BovaError("export does not match gasflaredb values")
    digest = sha256_file(out)
    man = {
        "export_file": out.name,
        "sha256": digest,
        "extracted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_database": _redact_url(dado),
        "gasflare_database": _redact_url(gas),
        "query_filter": {
            "ticker": "BOVA11",
            "tradedate_min": str(WINDOW_START),
            "tradedate_max": str(WINDOW_END),
            "table": "equity_daily",
        },
        "row_count": int(len(gas_df)),
        "date_min": str(min(gas_df["tradedate"])),
        "date_max": str(max(gas_df["tradedate"])),
        "price_convention": "B3 COTAHIST unadjusted closing price (price_last), BRL",
        "export_command": "./run_equity_daily_sync.sh --tickers BOVA11 --full-refresh ; python src/etapa4_petr4_bova11.py --export-supplement",
        "dado_rows_in_window": int(len(dado_df)),
        "source_match": True,
        "course_sqlite": CURRENT_FREEZE,
        "course_sqlite_sha256": CURRENT_SHA256,
    }
    manifest_path(root).write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", out, digest)
    return out


def _read_equity(con: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT * FROM equity_daily WHERE ticker = ? ORDER BY tradedate",
        con,
        params=(ticker,),
    )
    df["tradedate"] = pd.to_datetime(df["tradedate"])
    return df


def load_inputs(root: Path | None = None) -> dict:
    root = root or find_project_root()
    course = sqlite_file(CURRENT_FREEZE, root)
    bova = supplement_path(root)
    overlay = load_overlay(root)
    petr_raw = _read_equity(sqlite3.connect(f"file:{course.as_posix()}?mode=ro", uri=True), "PETR4")
    bov_raw = _read_equity(sqlite3.connect(f"file:{bova.as_posix()}?mode=ro", uri=True), "BOVA11")
    petr = apply_equity_overlay(petr_raw, "PETR4", overlay)
    bov = apply_equity_overlay(bov_raw, "BOVA11", overlay)
    engine = engine_for(course)
    ppi = pd.read_sql("SELECT report_date, pbr_gas_R, pbr_die_R FROM ppi_daily ORDER BY report_date", engine)
    ppi["report_date"] = pd.to_datetime(ppi["report_date"])
    sales = pd.read_sql("SELECT product, month, volume_m3 FROM anp_fuel_sales ORDER BY month, product", engine)
    sales["month"] = pd.to_datetime(sales["month"])
    return {
        "root": root,
        "course": course,
        "bova_path": bova,
        "petr4_snapshot": petr_raw,
        "bova11_snapshot": bov_raw,
        "petr4": petr,
        "bova11": bov,
        "ppi": ppi,
        "sales": sales,
        "overlay": overlay,
        "manifest": json.loads(manifest_path(root).read_text(encoding="utf-8")),
    }


def _ohlc_issues(df: pd.DataFrame) -> list[str]:
    issues = []
    px = df["price_last"].astype(float)
    if (px <= 0).any() or ~np.isfinite(px).all():
        issues.append("nonpositive or nonfinite price_last")
    for col in ("price_open", "price_max", "price_min"):
        if col in df and df[col].notna().any():
            bad = df[df[col].notna() & ((df[col] <= 0) | ~np.isfinite(df[col]))]
            if len(bad):
                issues.append(f"invalid {col}: {len(bad)}")
    if {"price_min", "price_max", "price_last"} <= set(df.columns):
        bad = df[
            df["price_min"].notna()
            & df["price_max"].notna()
            & ((df["price_last"] < df["price_min"] - 1e-9) | (df["price_last"] > df["price_max"] + 1e-9))
        ]
        if len(bad):
            issues.append(f"price_last outside high/low: {len(bad)}")
    return issues


def audit_inputs(raw: dict) -> dict:
    petr, bov = raw["petr4"].copy(), raw["bova11"].copy()
    petr_snap = raw["petr4_snapshot"].copy()
    bov_snap = raw["bova11_snapshot"].copy()
    overlay = raw["overlay"]
    issues: list[dict] = []

    def flag(ticker, dates, reason):
        for d in dates:
            issues.append({"ticker": ticker, "tradedate": str(pd.Timestamp(d).date()), "reason": reason})

    for ticker, df in (("PETR4", petr), ("BOVA11", bov)):
        if df["ticker"].nunique() != 1 or df["ticker"].iloc[0] != ticker:
            raise BovaError(f"unexpected ticker in {ticker} table")
        if df["tradedate"].duplicated().any():
            flag(ticker, df.loc[df["tradedate"].duplicated(), "tradedate"], "duplicate tradedate")
        issues.extend({"ticker": ticker, "tradedate": None, "reason": msg} for msg in _ohlc_issues(df))
    calendar = b3_session_index(WINDOW_START, WINDOW_END)
    p_dates = pd.DatetimeIndex(petr["tradedate"].sort_values()).normalize()
    b_dates = pd.DatetimeIndex(bov["tradedate"].sort_values()).normalize()
    snap_p = pd.DatetimeIndex(petr_snap["tradedate"].sort_values()).normalize()
    snap_b = pd.DatetimeIndex(bov_snap["tradedate"].sort_values()).normalize()
    only_p = p_dates.difference(b_dates)
    only_b = b_dates.difference(p_dates)
    if len(only_p):
        flag("BOVA11", only_p, "missing session present in PETR4")
    if len(only_b):
        flag("PETR4", only_b, "missing session present in BOVA11")
    common = p_dates.intersection(b_dates)
    missing_vs_cal_p = calendar.difference(p_dates)
    missing_vs_cal_b = calendar.difference(b_dates)
    extra_vs_cal_p = p_dates.difference(calendar)
    extra_vs_cal_b = b_dates.difference(calendar)
    snap_missing_cal = calendar.difference(snap_p.intersection(snap_b))
    if len(missing_vs_cal_p):
        flag("PETR4", missing_vs_cal_p, "missing B3 session vs independent calendar")
    if len(missing_vs_cal_b):
        flag("BOVA11", missing_vs_cal_b, "missing B3 session vs independent calendar")
    if len(extra_vs_cal_p):
        flag("PETR4", extra_vs_cal_p, "date outside independent B3 calendar")
    if len(extra_vs_cal_b):
        flag("BOVA11", extra_vs_cal_b, "date outside independent B3 calendar")
    overlay_dates = [str(r["tradedate"]) for r in overlay.get("rows", [])]

    sales = raw["sales"].copy()
    sales["period"] = pd.to_datetime(sales["month"]).dt.to_period("M")
    gas_m = sales.loc[sales["product"] == "gasolina_c"].set_index("period")["volume_m3"]
    die_m = sales.loc[sales["product"] == "diesel"].set_index("period")["volume_m3"]
    months_needed = pd.period_range("2022-04", "2026-06", freq="M")
    missing_vol = {
        "gasolina_c": [str(m) for m in months_needed if m not in gas_m.index or not np.isfinite(float(gas_m.loc[m]))],
        "diesel": [str(m) for m in months_needed if m not in die_m.index or not np.isfinite(float(die_m.loc[m]))],
    }
    ppi = raw["ppi"].set_index("report_date").sort_index()
    q1_base = petr.loc[petr["tradedate"] < "2022-04-01", "tradedate"]
    q1_ok = False
    if len(petr.loc[petr["tradedate"] < "2022-01-01"]):
        q1_ok = True
    audit = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_convention": "raw unadjusted B3 COTAHIST close; target is raw price-return differential, not total investment return",
        "corporate_actions": "source does not provide split or dividend adjustment factors; none were fabricated",
        "quantity_field": "total_quantity is share count, not financial volume",
        "petr4": {
            "n": int(len(petr)),
            "min": str(p_dates.min().date()),
            "max": str(p_dates.max().date()),
            "source": CURRENT_FREEZE,
            "sha256": CURRENT_SHA256,
        },
        "bova11": {
            "n": int(len(bov)),
            "min": str(b_dates.min().date()),
            "max": str(b_dates.max().date()),
            "source": raw["manifest"]["export_file"],
            "sha256": raw["manifest"]["sha256"],
        },
        "common_sessions": int(len(common)),
        "sessions_only_petr4": [str(d.date()) for d in only_p],
        "sessions_only_bova11": [str(d.date()) for d in only_b],
        "calendar": {
            "source": "ANBIMA national holidays plus B3 year-end closures (Christmas Eve and New Year bridge)",
            "n": int(len(calendar)),
            "min": str(calendar.min().date()),
            "max": str(calendar.max().date()),
            "missing_petr4": [str(d.date()) for d in missing_vs_cal_p],
            "missing_bova11": [str(d.date()) for d in missing_vs_cal_b],
            "extra_petr4": [str(d.date()) for d in extra_vs_cal_p],
            "extra_bova11": [str(d.date()) for d in extra_vs_cal_b],
        },
        "snapshots_before_overlay": {
            "petr4_n": int(len(petr_snap)),
            "bova11_n": int(len(bov_snap)),
            "common_n": int(len(snap_p.intersection(snap_b))),
            "missing_vs_calendar": [str(d.date()) for d in snap_missing_cal],
        },
        "overlay": {
            "file": overlay.get("path"),
            "sha256": overlay.get("sha256"),
            "tradedate": overlay.get("tradedate"),
            "dates": overlay_dates,
            "source": overlay.get("source"),
            "reason": overlay.get("reason"),
        },
        "issues": issues,
        "missing_volume_months_2022Q2_2026Q2": missing_vol,
        "ppi_range": [str(ppi.index.min().date()), str(ppi.index.max().date()), int(len(ppi))],
        "exclude_2022Q1": True,
        "q1_2022_base_available": q1_ok,
        "q1_2022_petr4_before_apr": int(len(q1_base)),
        "accepted": (
            len(only_p) == 0
            and len(only_b) == 0
            and len(missing_vs_cal_p) == 0
            and len(missing_vs_cal_b) == 0
            and len(extra_vs_cal_p) == 0
            and len(extra_vs_cal_b) == 0
            and not any(missing_vol.values())
            and not issues
        ),
        "limitations": [
            "Preços sem ajuste por proventos; datas de distribuição podem afetar o diferencial.",
            "A subtração do retorno do BOVA11 fixa o peso do referencial em um; não estima beta nem alfa.",
            "A viabilidade ex ante não foi auditada contra horários de divulgação.",
            "O pregão de 17 de novembro de 2023 entra por overlay a partir de B3DB tbl_cotahist; o freeze do curso e o suplemento original permanecem inalterados.",
        ],
    }
    if not audit["accepted"]:
        raise BovaError("audit rejected: " + json.dumps(audit["issues"][:8] + [{"missing_vol": missing_vol}], default=str))
    return audit


def aligned_panel(raw: dict) -> pd.DataFrame:
    petr = raw["petr4"].set_index("tradedate").sort_index()
    bov = raw["bova11"].set_index("tradedate").sort_index()
    petr.index = petr.index.normalize()
    bov.index = bov.index.normalize()
    idx = b3_session_index(WINDOW_START, WINDOW_END)
    panel = pd.DataFrame(index=idx)
    panel["petr4"] = petr.reindex(idx)["price_last"].astype(float)
    panel["bova11"] = bov.reindex(idx)["price_last"].astype(float)
    px_ok = np.isfinite(panel["petr4"]) & np.isfinite(panel["bova11"]) & (panel["petr4"] > 0) & (panel["bova11"] > 0)
    if not bool(px_ok.all()):
        missing = [str(ts.date()) for ts in panel.index[~px_ok]]
        raise BovaError("prices missing on calendar sessions: " + ",".join(missing[:12]))
    prev_ok = px_ok.shift(1, fill_value=False)
    pair_ok = px_ok & prev_ok
    r_p = panel["petr4"] / panel["petr4"].shift(1) - 1
    r_b = panel["bova11"] / panel["bova11"].shift(1) - 1
    panel["r_petr4"] = r_p.where(pair_ok)
    panel["r_bova11"] = r_b.where(pair_ok)
    panel["delta_r"] = (panel["r_petr4"] - panel["r_bova11"]).where(pair_ok)
    ppi = raw["ppi"].set_index("report_date").sort_index()
    ppi.index = ppi.index.normalize()
    panel = panel.join(ppi[["pbr_gas_R", "pbr_die_R"]], how="left")
    first_ppi = ppi.index.min()
    panel.loc[panel.index >= first_ppi, ["pbr_gas_R", "pbr_die_R"]] = panel.loc[
        panel.index >= first_ppi, ["pbr_gas_R", "pbr_die_R"]
    ].ffill()
    for k in range(1, 6):
        panel[f"ppi_gas_l{k}"] = panel["pbr_gas_R"].shift(k)
        panel[f"ppi_die_l{k}"] = panel["pbr_die_R"].shift(k)
    q = panel.index.to_period("Q")
    panel["quarter"] = q.astype(str)
    session = []
    last = None
    n = 0
    for qi in q:
        if qi != last:
            n = 1
            last = qi
        else:
            n += 1
        session.append(n)
    panel["quarter_session"] = session
    panel["quarter_session_sq"] = panel["quarter_session"] ** 2
    bases = {}
    for qi in q.unique():
        start = qi.start_time.normalize()
        before = panel.index[panel.index < start]
        bases[str(qi)] = before[-1] if len(before) else pd.NaT
    panel["base_date"] = [bases[str(qi)] for qi in q]
    panel["R_petr4_qtd"] = np.nan
    panel["R_bova11_qtd"] = np.nan
    valid_base = panel["base_date"].notna()
    panel.loc[valid_base, "R_petr4_qtd"] = (
        panel.loc[valid_base, "petr4"] / panel.loc[valid_base, "base_date"].map(lambda d: panel.loc[d, "petr4"]) - 1
    )
    panel.loc[valid_base, "R_bova11_qtd"] = (
        panel.loc[valid_base, "bova11"] / panel.loc[valid_base, "base_date"].map(lambda d: panel.loc[d, "bova11"]) - 1
    )
    panel["D_qtd"] = panel["R_petr4_qtd"] - panel["R_bova11_qtd"]
    sales = raw["sales"].copy()
    sales["period"] = pd.to_datetime(sales["month"]).dt.to_period("M")
    piv = sales.pivot(index="period", columns="product", values="volume_m3")
    period = panel.index.to_period("M")

    def _month_vol(product: str) -> pd.Series:
        if product not in piv.columns:
            return pd.Series(np.nan, index=panel.index)
        col = piv[product]
        return pd.Series(
            [float(col.loc[m]) if m in col.index and np.isfinite(col.loc[m]) else np.nan for m in period],
            index=panel.index,
        )

    gas_m3 = _month_vol("gasolina_c")
    die_m3 = _month_vol("diesel")
    days = panel.index.to_series().dt.days_in_month.astype(float)
    panel["vol_gas_l"] = gas_m3.astype(float) * e3.LITERS_PER_M3 / days
    panel["vol_die_l"] = die_m3.astype(float) * e3.LITERS_PER_M3 / days
    panel["E_gas"] = panel["pbr_gas_R"] * panel["vol_gas_l"] / MN
    panel["E_die"] = panel["pbr_die_R"] * panel["vol_die_l"] / MN
    # Accumulated exposure: skip no unknown rows; invalidate from first missing input in the quarter.
    c_gas, c_die = [], []
    last_q = None
    acc_g = acc_d = 0.0
    valid = True
    for ts, row in panel.iterrows():
        qi = str(ts.to_period("Q"))
        if qi != last_q:
            acc_g = acc_d = 0.0
            valid = True
            last_q = qi
        if not valid or not np.isfinite([row["E_gas"], row["E_die"]]).all():
            valid = False
            c_gas.append(np.nan)
            c_die.append(np.nan)
            continue
        acc_g += float(row["E_gas"])
        acc_d += float(row["E_die"])
        c_gas.append(acc_g)
        c_die.append(acc_d)
    panel["C_gas_qtd"] = c_gas
    panel["C_die_qtd"] = c_die
    panel["C_total_qtd"] = panel["C_gas_qtd"] + panel["C_die_qtd"]
    lag1, lag2 = [], []
    last_q = None
    hist = []
    for ts, val in panel["D_qtd"].items():
        qi = str(ts.to_period("Q"))
        if qi != last_q:
            hist = []
            last_q = qi
        lag1.append(0.0 if len(hist) < 1 else hist[-1])
        lag2.append(0.0 if len(hist) < 2 else hist[-2])
        hist.append(float(val) if np.isfinite(val) else np.nan)
    panel["y_lag1"] = lag1
    panel["y_lag2"] = lag2
    pers = []
    last_q = None
    prev = 0.0
    first = True
    for ts, val in panel["D_qtd"].items():
        qi = str(ts.to_period("Q"))
        if qi != last_q:
            pers.append(0.0)
            last_q = qi
            first = True
        else:
            pers.append(prev)
            first = False
        prev = float(val) if np.isfinite(val) else np.nan
    panel["D_qtd_pers"] = pers
    return panel


def _block_index(index: pd.Index, start: str, end: str) -> pd.Index:
    blk = index[(index >= start) & (index <= end)]
    return blk


def _pack_block(y: pd.Series, hat: np.ndarray, dates: pd.Index, alpha, train_idx) -> dict:
    yb = y.reindex(dates)
    rec = {
        "block_start": str(pd.Timestamp(dates[0]).date()),
        "block_end": str(pd.Timestamp(dates[-1]).date()),
        "horizon": "21d",
        "evaluation_block": "21d",
        "dates": [str(pd.Timestamp(t).date()) for t in dates],
        "actual": yb.astype(float).tolist(),
        "predicted": np.asarray(hat, float).tolist(),
        "training_dates": [str(pd.Timestamp(t).date()) for t in train_idx],
        "information": "one-step; observed lags updated within block",
        "alpha": alpha,
        **_score(yb, hat),
    }
    return rec


def eval_daily(panel: pd.DataFrame, ycol: str) -> dict:
    y = panel[ycol].astype(float)
    x_full = panel[[c for cols in A_GROUPS.values() for c in cols]]
    blocks = [_block_index(panel.index, a, b) for a, b in DAILY_BLOCKS]
    for blk in blocks:
        if len(blk) == 0:
            raise BovaError(f"empty daily block {blk}")
    prefixes = [("21d", 21)]
    ev = eval_named_groups(y, x_full, A_GROUPS, blocks, prefixes, min_train=40)
    ev["comparisons"] = {}
    for name in A_GROUPS:
        if name == "a_history":
            continue
        ev["comparisons"][name] = {
            "21d": {
                "control_group": "a_history",
                **summarize(ev["groups"][name], ev["groups"]["a_history"], "21d"),
            }
        }
    scored = []
    for blk in blocks:
        scored.extend([str(pd.Timestamp(t).date()) for t in blk])
    if len(scored) != 126:
        raise BovaError(f"Dimension A scored dates {len(scored)} != 126")
    zero_rows = []
    for blk in blocks:
        hat = np.zeros(len(blk))
        rec = _pack_block(y, hat, blk, None, y.index[y.index < blk[0]])
        rec["group"] = "zero"
        zero_rows.append(rec)
    ev["zero"] = zero_rows
    ev["n_scored"] = len(scored)
    return ev


def _simplicity_pick(summary: dict, groups: list[str], n_feat: dict) -> dict:
    rows = []
    for name in groups:
        node = summary[name]
        rows.append((name, node["median_RMSE"], n_feat[name]))
    finite = [r for r in rows if r[1] == r[1]]
    if not finite:
        return {"selected": None, "status": "undefined", "min_error_group": None}
    best = min(r[1] for r in finite)
    min_error_group = min(finite, key=lambda r: (r[1], r[0]))[0]
    near = [r for r in finite if r[1] <= best * 1.02 or (best == 0 and r[1] == 0)]
    if best == 0:
        return {
            "selected": min_error_group,
            "status": "zero_control_or_error",
            "min_RMSE": best,
            "min_error_group": min_error_group,
            "within_2pct": [r[0] for r in near],
        }
    fewest = min(r[2] for r in near)
    tied = [r for r in near if r[2] == fewest]
    base = {
        "min_RMSE": best,
        "min_error_group": min_error_group,
        "within_2pct": [r[0] for r in near],
        "n_feat_selected_class": fewest,
    }
    if len(tied) > 1:
        return {
            "selected": None,
            "status": "unresolved_tie",
            "candidates": [r[0] for r in tied],
            **base,
        }
    return {"selected": tied[0][0], "status": "simplicity", **base}


def roll_ridge_x(y_all: pd.Series, x_all: pd.DataFrame, train_idx, test_idx, alpha: float, min_obs: int = 20) -> np.ndarray:
    pack = x_all.join(y_all.rename("y"), how="left").dropna()
    eligible = pack.index.intersection(train_idx)
    if len(eligible) < min_obs:
        return np.full(len(test_idx), np.nan)
    X = pack.loc[eligible].drop(columns=["y"])
    y = pack.loc[eligible, "y"]
    beta, mu, sd, y_mean = fit_ridge(X.to_numpy(float), y.to_numpy(float), alpha)
    hats = []
    for t in test_idx:
        if t not in x_all.index:
            hats.append(np.nan)
            continue
        row = x_all.loc[t, X.columns].to_numpy(float)
        if not np.isfinite(row).all():
            hats.append(np.nan)
            continue
        hats.append(float(((row - mu) / sd) @ beta) + y_mean)
    return np.asarray(hats, float)


def pick_alpha_quarters(y: pd.Series, x: pd.DataFrame, train_quarters: list[pd.Index], min_train: int = 40) -> float:
    inner = train_quarters[-3:] if len(train_quarters) >= 4 else []
    best_a, best = ALPHAS[1], math.inf
    for alpha in ALPHAS:
        rmses = []
        for blk in inner:
            prior = []
            for q in train_quarters:
                if q[0] < blk[0]:
                    prior.append(q)
            if not prior:
                continue
            tr = prior[0]
            for extra in prior[1:]:
                tr = tr.union(extra)
            if len(tr) < min_train:
                continue
            hat = roll_ridge_x(y, x, tr, blk, alpha, min_obs=min_train)
            rmses.append(_score(y.reindex(blk), hat)["RMSE"])
        med = float(np.nanmedian(rmses)) if rmses else math.inf
        if med < best:
            best, best_a = med, alpha
    return best_a


def quarter_slices(panel: pd.DataFrame) -> dict[str, pd.Index]:
    out = {}
    for q, sub in panel.groupby(panel.index.to_period("Q")):
        label = str(q)
        if label == "2022Q1":
            continue
        if not np.isfinite(sub["D_qtd"]).all() or not np.isfinite(sub["C_total_qtd"]).all():
            continue
        if sub["base_date"].isna().any():
            continue
        out[label] = sub.index
    return out


def eval_quarterly(panel: pd.DataFrame) -> dict:
    y = panel["D_qtd"].astype(float)
    slices = quarter_slices(panel)
    missing = [q for q in EVAL_QUARTERS if q not in slices]
    if missing:
        raise BovaError(f"incomplete evaluation quarters: {missing}")
    ordered = [q for q in sorted(slices) if q >= "2022Q2"]
    results = {"groups": {name: [] for name in B_GROUPS}, "persistence": [], "zero": [], "comparisons": {}}
    for name, cols in B_GROUPS.items():
        x = panel[cols]
        for q in EVAL_QUARTERS:
            blk = slices[q]
            prior_labels = [lab for lab in ordered if lab < q]
            if len(prior_labels) < 4:
                raise BovaError(f"fewer than four training quarters before {q}")
            tr_parts = [slices[lab] for lab in prior_labels]
            tr = tr_parts[0]
            for extra in tr_parts[1:]:
                tr = tr.union(extra)
            alpha = pick_alpha_quarters(y, x, tr_parts, min_train=40)
            hat = roll_ridge_x(y, x, tr, blk, alpha, min_obs=40)
            yb = y.reindex(blk)
            pers = panel.loc[blk, "D_qtd_pers"].to_numpy(float)
            rec = {
                "block_start": str(pd.Timestamp(blk[0]).date()),
                "block_end": str(pd.Timestamp(blk[-1]).date()),
                "horizon": "quarter",
                "evaluation_block": "quarter",
                "quarter": q,
                "dates": [str(pd.Timestamp(t).date()) for t in blk],
                "actual": yb.tolist(),
                "predicted": hat.tolist(),
                "training_dates": [str(pd.Timestamp(t).date()) for t in tr],
                "information": "one-step within quarter; coefficients fixed; contemporaneous accumulated exposure",
                "alpha": alpha,
                "quarter_end_actual": float(yb.iloc[-1]),
                "quarter_end_predicted": float(hat[-1]),
                "quarter_end_error": float(yb.iloc[-1] - hat[-1]),
                **_score(yb, hat),
            }
            results["groups"][name].append(rec)
            if name == "b_clock":
                results["persistence"].append({
                    **{k: rec[k] for k in ("block_start", "block_end", "horizon", "evaluation_block", "quarter", "dates", "actual")},
                    "predicted": pers.tolist(),
                    "quarter_end_actual": float(yb.iloc[-1]),
                    "quarter_end_predicted": float(pers[-1]),
                    "quarter_end_error": float(yb.iloc[-1] - pers[-1]),
                    **_score(yb, pers),
                })
                zhat = np.zeros(len(blk))
                results["zero"].append({
                    **{k: rec[k] for k in ("block_start", "block_end", "horizon", "evaluation_block", "quarter", "dates", "actual")},
                    "predicted": zhat.tolist(),
                    **_score(yb, zhat),
                })
    for name, control in B_CONTROLS.items():
        results["comparisons"][name] = {
            "quarter": {
                "control_group": control,
                **summarize(results["groups"][name], results["groups"][control], "quarter"),
            }
        }
    return results


def _feat_count_a(name: str) -> int:
    return 2 + len(A_GROUPS[name])


def _feat_count_b(name: str) -> int:
    return len(B_GROUPS[name])


def _pct_points(values) -> list:
    return (np.asarray(values, float) * 100.0).tolist()


def prediction_rows(daily_diff, daily_petr, quarterly) -> list[dict]:
    rows = []
    for dim, payload, target in (
        ("daily_ppi", daily_diff, "ret_diff_petr4_bova11"),
        ("daily_petr4_only", daily_petr, "r_petr4"),
    ):
        for name, recs in payload["groups"].items():
            for rec in recs:
                for d, a, h in zip(rec["dates"], rec["actual"], rec["predicted"]):
                    rows.append({
                        "dimension": dim, "target": target, "group": name,
                        "block": f"{rec['block_start']}_{rec['block_end']}",
                        "date": d, "actual": a, "estimate": h, "error": a - h,
                    })
    for name, recs in quarterly["groups"].items():
        for rec in recs:
            for d, a, h in zip(rec["dates"], rec["actual"], rec["predicted"]):
                rows.append({
                    "dimension": "quarterly_accumulation",
                    "target": "ret_diff_qtd_petr4_bova11",
                    "group": name, "block": rec["quarter"],
                    "date": d, "actual": a, "estimate": h, "error": a - h,
                })
    return rows


def verify_identities(panel: pd.DataFrame, daily_ev: dict, q_ev: dict) -> list[str]:
    issues = []
    sample = panel.dropna(subset=["delta_r"]).iloc[40]
    t = sample.name
    prev = panel.index[panel.index.get_loc(t) - 1]
    r_p = panel.loc[t, "petr4"] / panel.loc[prev, "petr4"] - 1
    r_b = panel.loc[t, "bova11"] / panel.loc[prev, "bova11"] - 1
    if abs(r_p - sample["r_petr4"]) > 1e-12 or abs((r_p - r_b) - sample["delta_r"]) > 1e-12:
        issues.append("simple-return identity failed")
    # lag 1 PPI is previous session, not calendar day
    loc = panel.index.get_loc(t)
    if panel.iloc[loc]["ppi_gas_l1"] != panel.iloc[loc - 1]["pbr_gas_R"]:
        issues.append("PPI lag1 is not previous exchange session")
    if panel.iloc[loc]["ppi_gas_l5"] != panel.iloc[loc - 5]["pbr_gas_R"]:
        issues.append("PPI lag5 is not five sessions earlier")
    q = "2025Q2"
    sub = panel[panel["quarter"] == q]
    base = sub["base_date"].iloc[0]
    last = sub.index[-1]
    rp = panel.loc[last, "petr4"] / panel.loc[base, "petr4"] - 1
    rb = panel.loc[last, "bova11"] / panel.loc[base, "bova11"] - 1
    if abs(rp - sub["R_petr4_qtd"].iloc[-1]) > 1e-10 or abs((rp - rb) - sub["D_qtd"].iloc[-1]) > 1e-10:
        issues.append("quarter-to-date compounding identity failed")
    summed = float(sub["delta_r"].sum())
    if abs(summed - sub["D_qtd"].iloc[-1]) < 1e-8:
        issues.append("sum of daily differentials unexpectedly equals compounded D_qtd")
    if panel[panel.index.to_period("Q").astype(str) == "2022Q1"]["D_qtd"].notna().any():
        issues.append("2022Q1 should not have a valid D_qtd")
    n_a = sum(len(r["dates"]) for r in daily_ev["groups"]["a_history"])
    if n_a != 126:
        issues.append(f"A scored {n_a}")
    if len(q_ev["groups"]["b_clock"]) != 6:
        issues.append("B does not have six complete quarters")
    t17 = pd.Timestamp("2023-11-17")
    t16 = pd.Timestamp("2023-11-16")
    t20 = pd.Timestamp("2023-11-20")
    if t17 not in panel.index:
        issues.append("2023-11-17 is absent from the exchange calendar index")
    else:
        loc20 = panel.index.get_loc(t20)
        if panel.index[loc20 - 1] != t17:
            issues.append("previous session of 2023-11-20 is not 2023-11-17")
        r20 = panel.loc[t20, "petr4"] / panel.loc[t17, "petr4"] - 1
        if abs(r20 - panel.loc[t20, "r_petr4"]) > 1e-12:
            issues.append("2023-11-20 daily return does not use 2023-11-17")
        r_skip = panel.loc[t20, "petr4"] / panel.loc[t16, "petr4"] - 1
        if abs(r_skip - panel.loc[t20, "r_petr4"]) < 1e-8:
            issues.append("2023-11-20 daily return still equals the 16-to-20 multi-session change")
        if abs(panel.loc[t17, "ppi_gas_l1"] - panel.loc[t16, "pbr_gas_R"]) > 1e-12:
            issues.append("PPI lag1 on 2023-11-17 is not the previous session")
        if abs(panel.loc[t20, "ppi_gas_l1"] - panel.loc[t17, "pbr_gas_R"]) > 1e-12:
            issues.append("PPI lag1 on 2023-11-20 is not 2023-11-17")
    for closed in ("2022-12-30", "2023-12-29", "2024-12-24", "2024-12-31", "2025-12-24", "2025-12-31"):
        if pd.Timestamp(closed) in panel.index:
            issues.append(f"{closed} is a B3 year-end closure and must stay off the calendar")
    return issues


def training_lag_association(panel: pd.DataFrame, train_end: str = "2026-02-18") -> dict:
    """Training-only association of delta_r with lagged PPI. EDA; not a lag selector."""
    lag_cols = [f"ppi_{fuel}_l{k}" for k in range(1, 6) for fuel in ("gas", "die")]
    sub = panel.loc[panel.index <= train_end, ["delta_r", "pbr_gas_R", "pbr_die_R", *lag_cols]].dropna()
    rows = []
    y = sub["delta_r"].to_numpy(float)
    for k in range(1, 6):
        for fuel, col in (("gasolina", f"ppi_gas_l{k}"), ("diesel", f"ppi_die_l{k}")):
            x = sub[col].to_numpy(float)
            if len(x) < 8 or np.std(x) < 1e-15 or np.std(y) < 1e-15:
                corr = math.nan
            else:
                corr = float(np.corrcoef(x, y)[0, 1])
            rows.append({
                "fuel": fuel,
                "lag": k,
                "column": col,
                "n": int(len(sub)),
                "corr": corr,
                "mean_x": float(np.mean(x)),
                "mean_y": float(np.mean(y)),
            })
    return {
        "cutoff": train_end,
        "n_train": int(len(sub)),
        "by_fuel_lag": rows,
        "role": "exploratory EDA on the training sample before the first daily evaluation block",
        "not_used_for_selection": True,
    }


def qtd_increment_diagnostic(panel: pd.DataFrame) -> dict:
    """Per-quarter association of daily D_qtd increments with same-day exposure."""
    rows = []
    for q, sub in panel.groupby(panel.index.to_period("Q")):
        label = str(q)
        if label == "2022Q1":
            continue
        if not np.isfinite(sub["D_qtd"]).all():
            continue
        dD = sub["D_qtd"].diff()
        dD.iloc[0] = float(sub["D_qtd"].iloc[0])
        e_total = sub["E_gas"] + sub["E_die"]
        pack = pd.DataFrame({
            "dD": dD.to_numpy(float),
            "E_gas": sub["E_gas"].to_numpy(float),
            "E_die": sub["E_die"].to_numpy(float),
            "E_total": e_total.to_numpy(float),
        }).dropna()
        for fuel, col in (("gasolina", "E_gas"), ("diesel", "E_die"), ("total", "E_total")):
            x = pack[col].to_numpy(float)
            y = pack["dD"].to_numpy(float)
            if len(pack) < 8 or np.std(x) < 1e-15 or np.std(y) < 1e-15:
                corr = math.nan
            else:
                corr = float(np.corrcoef(x, y)[0, 1])
            same_sign = int(np.sum(np.sign(x) == np.sign(y)))
            rows.append({
                "quarter": label,
                "fuel": fuel,
                "n": int(len(pack)),
                "corr_dD_E": corr,
                "same_sign_n": same_sign,
                "same_sign_share": same_sign / len(pack) if len(pack) else math.nan,
            })
    return {
        "rows": rows,
        "role": "robustness diagnostic of daily increments; observations inside a quarter are not independent replications",
        "not_a_substitute_for_primary_target": True,
    }


def fig_daily_lags(daily_ev: dict, root: Path) -> tuple[Path, Path, Path]:
    rows = []
    names = [n for n in A_GROUPS if n != "a_history"]
    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    y = np.arange(len(names))[::-1]
    rels, maes, wins = [], [], []
    for name in names:
        cmp_ = daily_ev["comparisons"][name]["21d"]
        rels.append(100.0 * cmp_["rel_RMSE_vs_pers"])
        mae = 100.0 * (cmp_["persistence_median_MAE"] - cmp_["median_MAE"]) / cmp_["persistence_median_MAE"] if cmp_["persistence_median_MAE"] else math.nan
        maes.append(mae)
        wins.append(f"{cmp_['blocks_better_RMSE']}/{cmp_['n_blocks']}")
        for blk in cmp_["block_comparisons"]:
            rows.append({
                "grupo": name, "controle": "a_history",
                "inicio": blk["block_start"], "fim": blk["block_end"],
                "rmse_candidato": blk["candidate_RMSE"], "rmse_controle": blk["control_RMSE"],
                "mae_candidato": blk["candidate_MAE"], "mae_controle": blk["control_MAE"],
                "n": blk["n"],
            })
    ax.barh(y, rels, color=COLOR_PPI, height=0.55, zorder=3)
    ax.axvline(0, color=COLOR_ZERO, lw=1.1)
    ax.axvline(5, color="#9a9a9a", lw=1.0, ls=":")
    ax.set_yticks(y)
    ax.set_yticklabels([f"t−{n[-1]}" for n in names])
    ax.set_xlabel("Redução do RMSE mediano frente a a_history (%)  ·  positivo = menor erro")
    ax.set_title("E4-BOVA-A1 — defasagens 1 a 5 do PPI, diferencial diário")
    ax.grid(axis="x", alpha=0.25)
    xmax = max(rels + [8]) + 18
    ax.set_xlim(min(rels + [-5]) - 2, xmax)
    for yi, name, rel, mae, win in zip(y, names, rels, maes, wins):
        verb_r = "Redução" if rel > 0 else ("Aumento" if rel < 0 else "RMSE inalterado")
        verb_m = "Redução" if mae > 0 else ("Aumento" if mae < 0 else "MAE inalterado")
        ax.text(xmax - 17, yi, f"{verb_r} do RMSE: {abs(rel):.1f}%  ·  {win} blocos\n{verb_m} do MAE: {abs(mae):.1f}%  ·  frente a a_history",
                va="center", fontsize=7.8)
    _fonte(fig)
    fig.subplots_adjust(left=0.16, right=0.98, top=0.90, bottom=0.12)
    svg, png = save_figure(fig, "petr4_bova11_daily_lags", root)
    table = save_table(rows, "petr4_bova11_daily_lags", root)
    return svg, png, table


def fig_daily_temporal(panel: pd.DataFrame, daily_ev: dict, root: Path) -> tuple[Path, Path, Path]:
    rec_h = {r["block_start"]: r for r in daily_ev["groups"]["a_history"]}
    rec_p = {r["block_start"]: r for r in daily_ev["groups"]["a_ppi_l1"]}
    dates, actual, hhat, phat, zeros, blocks = [], [], [], [], [], []
    for i, rec in enumerate(daily_ev["groups"]["a_history"]):
        key = rec["block_start"]
        for d, a, hh, pp in zip(rec["dates"], rec["actual"], rec["predicted"], rec_p[key]["predicted"]):
            dates.append(pd.Timestamp(d))
            actual.append(100 * a)
            hhat.append(100 * hh)
            phat.append(100 * pp)
            zeros.append(0.0)
            blocks.append(i)
    records = list(zip(dates, actual, hhat, phat, blocks))
    fig = plt.figure(figsize=(13.33, 7.8))
    gs = GridSpec(2, 1, height_ratios=[3.1, 1.15], hspace=0.22, figure=fig)
    ax = fig.add_subplot(gs[0])
    ax_e = fig.add_subplot(gs[1], sharex=ax)
    by = {}
    for rec in records:
        by.setdefault(rec[4], []).append(rec)
    order = sorted(by)
    for i, bid in enumerate(order):
        pts = by[bid]
        left = pts[0][0] if i == 0 else by[order[i - 1]][-1][0] + (pts[0][0] - by[order[i - 1]][-1][0]) / 2
        right = pts[-1][0] if i == len(order) - 1 else pts[-1][0] + (by[order[i + 1]][0][0] - pts[-1][0]) / 2
        ax.axvspan(left, right, color="#f3f3f3" if i % 2 == 0 else "#dce6f2", zorder=0)
        ax_e.axvspan(left, right, color="#f3f3f3" if i % 2 == 0 else "#dce6f2", zorder=0)
        ax.text(left + (right - left) / 2, 1.02, f"Bloco {i + 1}", transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", fontsize=8.5, color="#4a4a4a", clip_on=False)
        if i:
            ax.axvline(left, color="#6a6a6a", lw=1.0, ls=(0, (4, 3)))
            ax_e.axvline(left, color="#6a6a6a", lw=1.0, ls=(0, (4, 3)))
    ax.plot(dates, actual, color=COLOR_OBS, marker="o", ms=3.2, lw=1.5, label="Observado")
    ax.plot(dates, zeros, color="#888", lw=1.0, ls=":", label="Zero")
    ax.plot(dates, hhat, color=COLOR_CTRL, marker="s", ms=3.0, lw=1.2, ls="--", label="Controle a_history")
    ax.plot(dates, phat, color=COLOR_PBR, marker="D", ms=3.0, lw=1.2, label="Ilustração a_ppi_l1")
    ax_e.plot(dates, np.asarray(actual) - np.asarray(hhat), color=COLOR_CTRL, marker="s", ms=2.8, lw=1.0, ls="--")
    ax_e.plot(dates, np.asarray(actual) - np.asarray(phat), color=COLOR_PBR, marker="D", ms=2.8, lw=1.0)
    ax_e.axhline(0, color=COLOR_ZERO, lw=1.6)
    ax.set_title("E4-BOVA-A2 — diferencial diário PETR4 − BOVA11", pad=26)
    ax.set_ylabel("Diferencial (p.p.)")
    ax.legend(loc="upper left", ncol=2, framealpha=0.92)
    ax.grid(axis="y", alpha=0.25)
    ax_e.set_ylabel("Erro (p.p.)")
    ax_e.grid(axis="y", alpha=0.25)
    ax_e.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m/%y"))
    ax.tick_params(labelbottom=False)
    ax.yaxis.set_label_coords(-0.07, 0.5)
    ax_e.yaxis.set_label_coords(-0.07, 0.5)
    _wrapped_note(ax_e, NOTE_A, y=-0.50)
    _fonte(fig)
    fig.subplots_adjust(left=0.11, right=0.98, top=0.86, bottom=0.24, hspace=0.18)
    svg, png = save_figure(fig, "petr4_bova11_daily_temporal", root)
    table = save_table(
        [{"data": str(d.date()), "observado_pp": a, "a_history_pp": h, "a_ppi_l1_pp": p} for d, a, h, p in zip(dates, actual, hhat, phat)],
        "petr4_bova11_daily_temporal",
        root,
    )
    return svg, png, table


def fig_qtd_paths(panel: pd.DataFrame, root: Path) -> tuple[Path, Path, Path]:
    fig = plt.figure(figsize=(13.33, 10.2))
    gs = GridSpec(6, 2, figure=fig, hspace=0.55, wspace=0.22)
    fig.suptitle("E4-BOVA-B1 — diferencial acumulado e exposição por trimestre", y=0.98)
    rows = []
    for i, q in enumerate(EVAL_QUARTERS):
        r0, c = divmod(i, 2)
        sub = panel[panel["quarter"] == q]
        ax = fig.add_subplot(gs[2 * r0, c])
        ax_e = fig.add_subplot(gs[2 * r0 + 1, c], sharex=ax)
        ax.plot(sub.index, 100 * sub["D_qtd"], color=COLOR_OBS, lw=1.4)
        ax.axhline(0, color=COLOR_ZERO, lw=0.8)
        ax_e.plot(sub.index, sub["C_total_qtd"], color=COLOR_CORR, lw=1.3, label="total")
        ax_e.plot(sub.index, sub["C_gas_qtd"], color=COLOR_PBR, lw=1.0, ls="--", label="gasolina")
        ax_e.plot(sub.index, sub["C_die_qtd"], color=COLOR_PPI, lw=1.0, ls=":", label="diesel")
        ax.set_title(q, fontsize=9, pad=2)
        ax.grid(alpha=0.25)
        ax_e.grid(alpha=0.25)
        ax.tick_params(labelbottom=False, labelsize=7)
        ax_e.tick_params(labelsize=7)
        ax_e.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
        ax_e.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        ax.set_ylabel("D_qtd (p.p.)", fontsize=8)
        ax_e.set_ylabel("Exposição (R$ mi)", fontsize=8)
        if i == 0:
            ax_e.legend(fontsize=6, loc="best")
        for ts, rec in sub.iterrows():
            rows.append({
                "quarter": q, "data": str(ts.date()),
                "D_qtd": rec["D_qtd"], "C_total_qtd": rec["C_total_qtd"],
                "C_gas_qtd": rec["C_gas_qtd"], "C_die_qtd": rec["C_die_qtd"],
            })
    _fonte(fig)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.94, bottom=0.06)
    svg, png = save_figure(fig, "petr4_bova11_qtd_paths", root)
    table = save_table(rows, "petr4_bova11_qtd_paths", root)
    return svg, png, table


def fig_qtd_temporal(panel: pd.DataFrame, q_ev: dict, root: Path) -> tuple[Path, Path, Path]:
    rec_c = {r["quarter"]: r for r in q_ev["groups"]["b_history_clock"]}
    rec_p = {r["quarter"]: r for r in q_ev["groups"]["b_history_clock_prod"]}
    fig = plt.figure(figsize=(13.33, 7.5))
    gs = GridSpec(2, 1, height_ratios=[3.1, 1.15], hspace=0.12, figure=fig)
    ax = fig.add_subplot(gs[0])
    ax_e = fig.add_subplot(gs[1], sharex=ax)
    first = True
    rows = []
    for q in EVAL_QUARTERS:
        rec = rec_c[q]
        dates = pd.to_datetime(rec["dates"])
        actual = 100 * np.asarray(rec["actual"], float)
        hist = 100 * np.asarray(rec["predicted"], float)
        prod = 100 * np.asarray(rec_p[q]["predicted"], float)
        pers = 100 * panel.loc[dates, "D_qtd_pers"].to_numpy(float)
        ax.plot(dates, actual, color=COLOR_OBS, lw=1.5, marker="o", ms=2.4, label="Observado" if first else None)
        ax.plot(dates, pers, color="#888", lw=1.0, ls=":", label="Persistência com reset" if first else None)
        ax.plot(dates, hist, color=COLOR_CTRL, lw=1.2, ls="--", marker="s", ms=2.2, label="b_history_clock" if first else None)
        ax.plot(dates, prod, color=COLOR_CORR, lw=1.2, marker="D", ms=2.2, label="Ilustração b_history_clock_prod" if first else None)
        ax_e.plot(dates, actual - hist, color=COLOR_CTRL, lw=1.0, ls="--", marker="s", ms=2.0)
        ax_e.plot(dates, actual - prod, color=COLOR_CORR, lw=1.0, marker="D", ms=2.0)
        first = False
        for d, a, h, p in zip(dates, actual, hist, prod):
            rows.append({"quarter": q, "data": str(d.date()), "observado_pp": a, "b_history_clock_pp": h, "b_history_clock_prod_pp": p})
    ax.axhline(0, color=COLOR_ZERO, lw=1.0)
    ax_e.axhline(0, color=COLOR_ZERO, lw=1.6)
    ax.set_title("E4-BOVA-B2 — diferencial acumulado no trimestre", pad=12)
    ax.set_ylabel("D_qtd (pontos percentuais)")
    ax.legend(loc="upper left", ncol=2, framealpha=0.92)
    ax.grid(axis="y", alpha=0.25)
    ax_e.set_ylabel("Erro: observado − estimado")
    ax_e.grid(axis="y", alpha=0.25)
    ax_e.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    ax.tick_params(labelbottom=False)
    _wrapped_note(ax_e, NOTE_B, y=-0.45)
    _fonte(fig)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.90, bottom=0.22)
    svg, png = save_figure(fig, "petr4_bova11_qtd_temporal", root)
    table = save_table(rows, "petr4_bova11_qtd_temporal", root)
    return svg, png, table


def fig_qtd_blocks(q_ev: dict, root: Path) -> tuple[Path, Path, Path]:
    fig, axes = plt.subplots(2, 1, figsize=(13.33, 7.5), sharex=True)
    fig.suptitle("E4-BOVA-B3 — RMSE por trimestre e erro no fechamento")
    names = ["b_history_clock_prod", "b_history_clock_fuels"]
    x = np.arange(len(EVAL_QUARTERS))
    width = 0.35
    rows = []
    ax = axes[0]
    for i, name in enumerate(names):
        cmp_ = q_ev["comparisons"][name]["quarter"]
        rel = [100.0 * (b["control_RMSE"] - b["candidate_RMSE"]) / b["control_RMSE"] if b["control_RMSE"] else math.nan
               for b in cmp_["block_comparisons"]]
        ax.bar(x + (i - 0.5) * width, rel, width=width, label=name, zorder=3)
        for q, blk in zip(EVAL_QUARTERS, cmp_["block_comparisons"]):
            rows.append({"grupo": name, "quarter": q, **blk})
    ax.axhline(0, color=COLOR_ZERO, lw=1.0)
    ax.axhline(5, color="#9a9a9a", ls=":", lw=1.0)
    ax.set_ylabel("Redução do RMSE\nfrente a b_history_clock (%)")
    ax.legend(loc="best")
    ax.grid(axis="y", alpha=0.25)
    ax2 = axes[1]
    for name, color in (("b_history_clock", COLOR_CTRL), ("b_history_clock_prod", COLOR_CORR)):
        end_err = [100 * r["quarter_end_error"] for r in q_ev["groups"][name]]
        ax2.plot(x, end_err, marker="o", lw=1.4, color=color, label=name)
    ax2.axhline(0, color=COLOR_ZERO, lw=1.0)
    ax2.set_xticks(x)
    ax2.set_xticklabels(EVAL_QUARTERS)
    ax2.set_ylabel("Erro no fechamento do trimestre (p.p.)")
    ax2.legend(loc="best")
    ax2.grid(axis="y", alpha=0.25)
    _fonte(fig)
    fig.subplots_adjust(left=0.10, right=0.98, top=0.90, bottom=0.12, hspace=0.22)
    svg, png = save_figure(fig, "petr4_bova11_qtd_blocks", root)
    table = save_table(rows, "petr4_bova11_qtd_blocks", root)
    return svg, png, table


def write_charts(panel, daily_ev, q_ev, root) -> dict:
    _style()
    return {
        "petr4_bova11_daily_lags": fig_daily_lags(daily_ev, root),
        "petr4_bova11_daily_temporal": fig_daily_temporal(panel, daily_ev, root),
        "petr4_bova11_qtd_paths": fig_qtd_paths(panel, root),
        "petr4_bova11_qtd_temporal": fig_qtd_temporal(panel, q_ev, root),
        "petr4_bova11_qtd_blocks": fig_qtd_blocks(q_ev, root),
    }


def rebuild(root: Path | None = None) -> dict:
    root = root or find_project_root()
    raw = load_inputs(root)
    audit = audit_inputs(raw)
    panel = aligned_panel(raw)
    daily = eval_daily(panel, "delta_r")
    petr_only = eval_daily(panel, "r_petr4")
    quarterly = eval_quarterly(panel)
    issues = verify_identities(panel, daily, quarterly)
    if issues:
        raise BovaError("verification failed: " + "; ".join(issues))
    assoc = training_lag_association(panel)
    incr = qtd_increment_diagnostic(panel)
    a_sum = {n: summarize(daily["groups"][n], daily["groups"]["a_history"] if n != "a_history" else daily["persistence"], "21d")
             for n in A_GROUPS}
    a_sum["a_history"] = summarize(daily["groups"]["a_history"], daily["persistence"], "21d")
    pick_a = _simplicity_pick(
        {n: daily["comparisons"][n]["21d"] for n in daily["comparisons"]},
        [n for n in A_GROUPS if n != "a_history"],
        {n: _feat_count_a(n) for n in A_GROUPS},
    )
    b_sum = {n: quarterly["comparisons"][n]["quarter"] if n in quarterly["comparisons"] else summarize(quarterly["groups"][n], quarterly["persistence"], "quarter")
             for n in B_GROUPS}
    pick_b = _simplicity_pick(
        {n: (quarterly["comparisons"][n]["quarter"] if n in quarterly["comparisons"]
             else summarize(quarterly["groups"][n], quarterly["persistence"], "quarter"))
         for n in B_GROUPS},
        list(B_GROUPS),
        {n: _feat_count_b(n) for n in B_GROUPS},
    )
    a_hist_vs_zero = summarize(daily["groups"]["a_history"], daily["zero"], "21d")
    a_zero_self = summarize(daily["zero"], daily["zero"], "21d")
    a_pers_self = summarize(daily["persistence"], daily["persistence"], "21d")
    b_hist_vs_pers = summarize(quarterly["groups"]["b_history_clock"], quarterly["persistence"], "quarter")
    b_clock_vs_pers = summarize(quarterly["groups"]["b_clock"], quarterly["persistence"], "quarter")
    b_prod_vs_pers = summarize(quarterly["groups"]["b_history_clock_prod"], quarterly["persistence"], "quarter")
    b_zero_self = summarize(quarterly["zero"], quarterly["zero"], "quarter")
    b_pers_self = summarize(quarterly["persistence"], quarterly["persistence"], "quarter")
    pred_rows = prediction_rows(daily, petr_only, quarterly)
    pred_path = results_dir(root) / "etapa4_petr4_bova11_predictions.csv"
    with pred_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(pred_rows[0].keys()))
        writer.writeheader()
        writer.writerows(pred_rows)
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "experiment": "PETR4 versus BOVA11: daily lagged plain PPI and quarterly accumulated exposure",
        "information": "Dimension A: lagged PPI, not contemporaneous. Dimension B: contemporaneous accumulated PPI × volume, descriptive.",
        "ex_ante": "not evaluated",
        "price_convention": audit["price_convention"],
        "inputs": {
            "course_sqlite": CURRENT_FREEZE,
            "course_sha256": CURRENT_SHA256,
            "bova11_file": raw["manifest"]["export_file"],
            "bova11_sha256": raw["manifest"]["sha256"],
            "overlay_file": raw["overlay"]["path"],
            "overlay_sha256": raw["overlay"]["sha256"],
            "overlay_tradedate": raw["overlay"]["tradedate"],
            "calendar_n": audit["calendar"]["n"],
        },
        "daily_ppi": {
            "target": "ret_diff_petr4_bova11",
            "groups": A_GROUPS,
            "blocks": [f"{a}..{b}" for a, b in DAILY_BLOCKS],
            "n_scored": daily["n_scored"],
            "rows": daily,
            "summary": {n: summarize(daily["groups"][n], daily["groups"]["a_history"], "21d") if n != "a_history" else summarize(daily["groups"][n], daily["persistence"], "21d") for n in A_GROUPS},
            "selection": pick_a,
            "criterion": {n: daily["comparisons"][n]["21d"]["promote_ge_5pct"] for n in daily["comparisons"]},
            "references": {
                "zero": a_zero_self,
                "persistence": a_pers_self,
                "a_history_vs_zero": a_hist_vs_zero,
                "a_history_vs_persistence": a_sum["a_history"],
            },
            "training_lag_association": assoc,
            "petr4_only_diagnostic": {
                "summary": {n: summarize(petr_only["groups"][n], petr_only["groups"]["a_history"], "21d") if n != "a_history" else summarize(petr_only["groups"][n], petr_only["persistence"], "21d") for n in A_GROUPS},
            },
        },
        "quarterly_accumulation": {
            "target": "ret_diff_qtd_petr4_bova11",
            "groups": B_GROUPS,
            "quarters": list(EVAL_QUARTERS),
            "exclude": "2022Q1",
            "partial_not_scored": "2026Q3",
            "rows": quarterly,
            "summary": {n: (quarterly["comparisons"][n]["quarter"] if n in quarterly["comparisons"] else summarize(quarterly["groups"][n], quarterly["persistence"], "quarter")) for n in B_GROUPS},
            "selection": pick_b,
            "criterion": {n: quarterly["comparisons"][n]["quarter"]["promote_ge_5pct"] for n in quarterly["comparisons"]},
            "references": {
                "zero": b_zero_self,
                "persistence": b_pers_self,
                "b_clock_vs_persistence": b_clock_vs_pers,
                "b_history_clock_vs_persistence": b_hist_vs_pers,
                "b_history_clock_prod_vs_persistence": b_prod_vs_pers,
            },
            "increment_diagnostic": incr,
        },
        "limitations": audit["limitations"],
        "verification_ok": True,
    }
    (results_dir(root) / "etapa4_petr4_bova11_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    (results_dir(root) / "etapa4_petr4_bova11.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    write_charts(panel, daily, quarterly, root)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-supplement", action="store_true")
    args = parser.parse_args()
    root = find_project_root()
    if args.export_supplement:
        export_supplement(root)
        return
    report = rebuild(root)
    print("daily n", report["daily_ppi"]["n_scored"])
    print("daily criterion", report["daily_ppi"]["criterion"])
    print("daily selection", report["daily_ppi"]["selection"])
    print("quarter criterion", report["quarterly_accumulation"]["criterion"])
    print("quarter selection", report["quarterly_accumulation"]["selection"])
    print("wrote results/etapa4_petr4_bova11.json")


if __name__ == "__main__":
    main()
