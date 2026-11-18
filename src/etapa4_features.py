"""Exposure variants for Etapa 4. Does not change etapa3_models.py.

Scale monetary exposure to R$ millions. Combined ``prod`` stays the
Etapa 3 reference (also stored unscaled on the daily frame).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import etapa3_models as e3
from etapa4_data import engine_for

MN = 1_000_000.0


def add_exposure_variants(frames: dict) -> dict:
    daily = frames["daily"].copy()
    daily["prod_gas"] = daily["pbr_gas_R"] * daily["vol_gas_l"]
    daily["prod_die"] = daily["pbr_die_R"] * daily["vol_die_l"]
    daily["prod_mn"] = daily["prod"] / MN
    daily["prod_gas_mn"] = daily["prod_gas"] / MN
    daily["prod_die_mn"] = daily["prod_die"] / MN
    daily["dprod_mn"] = daily["prod_mn"].diff()
    daily["prod_mn_t5"] = daily["prod_mn"].rolling(5, min_periods=5).sum()
    daily["prod_mn_t21"] = daily["prod_mn"].rolling(21, min_periods=21).sum()
    daily["prod_pos_mn"] = daily["prod_mn"].clip(lower=0.0)
    daily["prod_neg_mn"] = daily["prod_mn"].clip(upper=0.0)

    price = frames["price_week"].copy()
    daily_w = (
        daily[["prod_mn", "prod_gas_mn", "prod_die_mn", "dprod_mn"]]
        .resample("W-MON", closed="left", label="left")
        .mean()
    )
    for col in daily_w.columns:
        if col not in price.columns:
            price[col] = daily_w[col]
    price[["prod_mn", "prod_gas_mn", "prod_die_mn", "dprod_mn"]] = price[
        ["prod_mn", "prod_gas_mn", "prod_die_mn", "dprod_mn"]
    ].ffill()
    price["prod_mn_t4"] = price["prod_mn"].rolling(4, min_periods=4).sum()
    price["prod_mn_t8"] = price["prod_mn"].rolling(8, min_periods=8).sum()
    posneg = (
        daily[["prod_pos_mn", "prod_neg_mn", "prod_gas_mn", "prod_die_mn"]]
        .assign(
            prod_gas_pos_mn=lambda d: d["prod_gas_mn"].clip(lower=0.0),
            prod_gas_neg_mn=lambda d: d["prod_gas_mn"].clip(upper=0.0),
            prod_die_pos_mn=lambda d: d["prod_die_mn"].clip(lower=0.0),
            prod_die_neg_mn=lambda d: d["prod_die_mn"].clip(upper=0.0),
        )
        .resample("W-MON", closed="left", label="left")
        .mean()
    )
    for col in (
        "prod_pos_mn",
        "prod_neg_mn",
        "prod_gas_pos_mn",
        "prod_gas_neg_mn",
        "prod_die_pos_mn",
        "prod_die_neg_mn",
    ):
        price[col] = posneg[col]
    for k in range(0, 9):
        price[f"prod_gas_mn_l{k}"] = price["prod_gas_mn"].shift(k)
        price[f"prod_die_mn_l{k}"] = price["prod_die_mn"].shift(k)
    price["danp_gas"] = price["anp_gas"].diff()
    price["danp_die"] = price["anp_die"].diff()
    price["dpbr_gas"] = price["pbr_gas"].diff()
    price["dpbr_die"] = price["pbr_die"].diff()
    price["spread_gas"] = price["anp_gas"] - price["pbr_gas"]
    price["spread_die"] = price["anp_die"] - price["pbr_die"]

    monthly = frames["monthly"].copy()
    msum = daily[["prod_mn", "prod_gas_mn", "prod_die_mn", "prod_pos_mn", "prod_neg_mn"]].resample("MS").sum()
    for col in msum.columns:
        monthly[col] = msum[col]
    monthly["dprod_mn"] = monthly["prod_mn"].diff()
    monthly["prod_mn_t3"] = monthly["prod_mn"].rolling(3, min_periods=3).sum()
    monthly["prod_gas_pos_mn"] = monthly["prod_gas_mn"].clip(lower=0.0)
    monthly["prod_gas_neg_mn"] = monthly["prod_gas_mn"].clip(upper=0.0)
    monthly["prod_die_pos_mn"] = monthly["prod_die_mn"].clip(lower=0.0)
    monthly["prod_die_neg_mn"] = monthly["prod_die_mn"].clip(upper=0.0)
    for k in range(0, 4):
        monthly[f"prod_gas_mn_l{k}"] = monthly["prod_gas_mn"].shift(k)
        monthly[f"prod_die_mn_l{k}"] = monthly["prod_die_mn"].shift(k)
    daily["dlog_petr4"] = np.log(daily["petr4"].astype(float)).diff()
    daily["rv5"] = daily["dlog_petr4"].rolling(5, min_periods=5).std()
    daily["rv21"] = daily["dlog_petr4"].rolling(21, min_periods=21).std()

    # Light traffic, ANP demand, inflation, equity volume (not in Etapa 3 panels).
    sqlite_path = frames.get("sqlite_path")
    engine = engine_for(Path(sqlite_path)) if sqlite_path else e3.read_engine(frames.get("root"))
    abcr = e3._sql(engine, "SELECT month, vehicle_type, traffic_index FROM abcr_traffic_index")
    abcr["month"] = pd.to_datetime(abcr["month"])
    light = (
        abcr[abcr["vehicle_type"] == "light"]
        .set_index("month")
        .sort_index()["traffic_index"]
        .rename("abcr_light")
    )
    sales = e3._sql(engine, "SELECT product, month, volume_m3 FROM anp_fuel_sales")
    sales["month"] = pd.to_datetime(sales["month"])
    sales_w = sales.pivot(index="month", columns="product", values="volume_m3").sort_index()
    monthly["abcr_light"] = light
    monthly["anp_gas_m3"] = sales_w.get("gasolina_c")
    monthly["anp_die_m3"] = sales_w.get("diesel")
    monthly["month_num"] = monthly.index.month.astype(float)
    for k in range(0, 4):
        monthly[f"prod_mn_l{k}"] = monthly["prod_mn"].shift(k)
    anp_m = price[["anp_gas", "anp_die"]].resample("MS").mean()
    monthly["anp_gas_m"] = anp_m["anp_gas"]
    monthly["anp_die_m"] = anp_m["anp_die"]
    monthly["danp_gas"] = monthly["anp_gas_m"].diff()
    monthly["danp_die"] = monthly["anp_die_m"].diff()
    inf = e3._sql(engine, "SELECT series, metric, month, value FROM inflation_monthly WHERE metric='mom_pct'")
    inf["month"] = pd.to_datetime(inf["month"])
    inf_w = inf.pivot(index="month", columns="series", values="value").sort_index()
    monthly["ipca"] = inf_w.get("ipca")
    monthly["ipca15"] = inf_w.get("ipca15")
    monthly["igpm"] = inf_w.get("igpm")
    eqx = e3._sql(
        engine,
        "SELECT tradedate, total_quantity FROM equity_daily WHERE ticker='PETR4' ORDER BY tradedate",
    )
    eqx["tradedate"] = pd.to_datetime(eqx["tradedate"])
    eqx = eqx.set_index("tradedate").sort_index()
    daily["qty_mn"] = eqx["total_quantity"] / MN
    daily["dqty_mn"] = daily["qty_mn"].diff()

    ppi_ind = e3._sql(
        engine,
        "SELECT report_date, ind_gas_R, ind_die_R FROM ppi_daily ORDER BY report_date",
    )
    ppi_ind["report_date"] = pd.to_datetime(ppi_ind["report_date"])
    ppi_ind = ppi_ind.set_index("report_date").sort_index()
    daily["ind_gas_R"] = ppi_ind["ind_gas_R"]
    daily["ind_die_R"] = ppi_ind["ind_die_R"]
    daily[["ind_gas_R", "ind_die_R"]] = daily[["ind_gas_R", "ind_die_R"]].ffill()
    daily["gap_gas_R"] = daily["ind_gas_R"] - daily["pbr_gas_R"]
    daily["gap_die_R"] = daily["ind_die_R"] - daily["pbr_die_R"]
    daily["prod_ind_gas_mn"] = daily["ind_gas_R"] * daily["vol_gas_l"] / MN
    daily["prod_ind_die_mn"] = daily["ind_die_R"] * daily["vol_die_l"] / MN
    daily["prod_ind_mn"] = daily["prod_ind_gas_mn"] + daily["prod_ind_die_mn"]
    ind_w = daily[
        [
            "ind_gas_R",
            "ind_die_R",
            "gap_gas_R",
            "gap_die_R",
            "prod_ind_gas_mn",
            "prod_ind_die_mn",
            "prod_ind_mn",
        ]
    ].resample("W-MON", closed="left", label="left").mean()
    for col in ind_w.columns:
        price[col] = ind_w[col]
    for k in range(0, 5):
        price[f"gap_gas_R_l{k}"] = price["gap_gas_R"].shift(k)
        price[f"gap_die_R_l{k}"] = price["gap_die_R"].shift(k)
        price[f"prod_ind_gas_mn_l{k}"] = price["prod_ind_gas_mn"].shift(k)
        price[f"prod_ind_die_mn_l{k}"] = price["prod_ind_die_mn"].shift(k)

    fin = frames["fin"].copy()
    # Daily prod_pbr split: same construction as etapa3, summed on the quarter.
    # Company exposure uses mbpd path already in prod_pbr. Split by fuel share of daily prod_pbr.
    # Rebuild prod_pbr components from the same liters-per-mbpd formula.
    # load_frames stored only prod_pbr. Reconstruct from PPI × last mbpd on the day.
    qend = pd.DatetimeIndex(daily.index.to_period("Q").end_time).normalize()
    mbpd = fin[["diesel_mbpd", "gasoline_mbpd"]].copy()
    mbpd_d = pd.DataFrame({"qend": qend}, index=daily.index).join(mbpd, on="qend")
    mbpd_d[["diesel_mbpd", "gasoline_mbpd"]] = mbpd_d[["diesel_mbpd", "gasoline_mbpd"]].ffill()
    daily["prod_pbr_gas"] = daily["pbr_gas_R"] * mbpd_d["gasoline_mbpd"] * e3.LITERS_PER_MBPD
    daily["prod_pbr_die"] = daily["pbr_die_R"] * mbpd_d["diesel_mbpd"] * e3.LITERS_PER_MBPD
    daily["prod_pbr_mn"] = daily["prod_pbr"] / MN
    daily["prod_pbr_gas_mn"] = daily["prod_pbr_gas"] / MN
    daily["prod_pbr_die_mn"] = daily["prod_pbr_die"] / MN
    q = daily[["prod_pbr_mn", "prod_pbr_gas_mn", "prod_pbr_die_mn"]].resample("QE-DEC").sum()
    fin = fin.join(q)

    out = dict(frames)
    out["daily"] = daily
    out["price_week"] = price
    out["monthly"] = monthly
    out["fin"] = fin
    out["mkt_train"] = daily.loc[: e3.MKT_TRAIN_END]
    out["mkt_test"] = e3.after(daily, e3.MKT_TRAIN_END).loc[: e3.MKT_TEST_END]
    out["price_train"] = price.loc[: e3.PRICE_TRAIN_END]
    out["price_test"] = e3.after(price, e3.PRICE_TRAIN_END).loc[: e3.PRICE_TEST_END]
    out["act_train"] = monthly.loc[: e3.ACT_TRAIN_END]
    out["act_test"] = e3.after(monthly, e3.ACT_TRAIN_END).loc[: e3.ACT_TEST_END]
    out["comp_train"] = fin.loc[: e3.COMP_TRAIN_END]
    out["comp_test"] = e3.after(fin, e3.COMP_TRAIN_END)
    return out
