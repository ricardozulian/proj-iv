"""Regression tests for comparable one-step evaluation and promotion rules."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import etapa4_matrix as matrix
from etapa4_data import CURRENT_FREEZE, load_frames_at, sqlite_file
from etapa4_features import add_exposure_variants
from etapa4_company import pack_corr, residual_correction
from etapa4_delivery import residual_sensitivity_rows
from etapa4_finance_baseline import (
    arima_orders,
    enumerate_configs,
    forecast_one,
    sarima_orders,
)
from etapa4_prod_contrib import eval_named_groups, one_step_persistence, summarize


def test_dummy_updates_inside_block():
    y = pd.Series([10.0, 20.0, 30.0, 40.0], index=pd.date_range("2024-01-01", periods=4))
    assert one_step_persistence(y, y.index[1:]).tolist() == [10.0, 20.0, 30.0]


def test_groups_use_identical_training_and_evaluation_dates():
    dates = pd.date_range("2024-01-01", periods=80)
    y = pd.Series(np.arange(80.0) + np.sin(np.arange(80.0)), index=dates)
    x = pd.DataFrame({"x": np.cos(np.arange(80.0))}, index=dates)
    x.loc[dates[:4], "x"] = np.nan
    result = eval_named_groups(y, x, {"y_only": [], "y_exp": ["x"]}, [dates[-4:]], [("4d", 4)], min_train=20)
    a, b = (result["groups"][g][0] for g in ("y_only", "y_exp"))
    assert a["dates"] == b["dates"] == result["persistence"][0]["dates"]
    assert a["training_dates"] == b["training_dates"]
    assert max(a["training_dates"]) < min(a["dates"])
    assert result["persistence"][0]["predicted"] == y.shift(1).iloc[-4:].tolist()
    assert result["comparisons"]["y_exp"]["4d"]["control_group"] == "y_only"


def test_summarize_rejects_different_observations():
    row = dict(block_start="2024-01-01", block_end="2024-01-02", horizon="2d", RMSE=1.0, MAE=1.0, n=2, dates=["2024-01-01", "2024-01-02"])
    with pytest.raises(ValueError, match="observations differ"):
        summarize([row], [{**row, "dates": ["2024-01-02", "2024-01-03"]}], "2d")


def test_promotion_uses_control_mae_and_wins_not_dummy():
    candidate = {"MAE": 1.0, "dummy_MAE": 100.0, "incremental": {
        "rel_RMSE_vs_pers": .10, "median_MAE": 1.0, "persistence_median_MAE": .9,
        "blocks_better_RMSE": 4, "n_blocks": 4}}
    assert matrix.contributes(candidate, {}, {}, False) == "não"
    candidate["incremental"]["persistence_median_MAE"] = 1.1
    candidate["incremental"]["blocks_better_RMSE"] = 2
    assert matrix.contributes(candidate, {}, {}, False) == "não"
    candidate["incremental"]["blocks_better_RMSE"] = 3
    assert matrix.contributes(candidate, {}, {}, False) == "sim"


def test_two_percent_tie_prefers_simpler_model():
    simple = {"group": "y_exp0", "family": "ppi_x_vol", "RMSE": 100.0, "complexity": 3}
    complex_ = {"group": "y_exp_l08", "family": "ppi_x_vol", "RMSE": 99.0, "complexity": 11}
    assert matrix._min_rmse([complex_, simple]) == simple
    complex_["RMSE"] = 95.0
    assert matrix._min_rmse([complex_, simple]) == complex_


def test_context_plus_exposure_uses_same_context_control():
    dates = pd.date_range("2024-01-01", periods=80)
    y = pd.Series(np.arange(80.0), index=dates)
    x = pd.DataFrame({"dqty": np.sin(np.arange(80.0)), "exposure": np.cos(np.arange(80.0))}, index=dates)
    result = eval_named_groups(y, x, {"y_only": [], "y_dqty": ["dqty"], "y_dprod_dqty": ["exposure", "dqty"]}, [dates[-4:]], [("4d", 4)], min_train=20)
    assert result["comparisons"]["y_dprod_dqty"]["4d"]["control_group"] == "y_dqty"


def test_current_target_does_not_change_its_own_prediction():
    from etapa4_prod_contrib import roll_ridge

    dates = pd.date_range("2024-01-01", periods=60)
    y = pd.Series(np.sin(np.arange(60.0)) + 10, index=dates)
    x = pd.DataFrame(index=dates)
    original = roll_ridge(y, x, dates[:50], dates[50:51], 1.0)
    changed = y.copy()
    changed.iloc[50:] += 1000
    assert roll_ridge(changed, x, dates[:50], dates[50:51], 1.0) == pytest.approx(original)


def test_weekly_exposure_is_monday_through_sunday():
    root = Path(__file__).resolve().parents[1]
    frames = add_exposure_variants(load_frames_at(sqlite_file(CURRENT_FREEZE, root), root))
    start = pd.Timestamp("2025-06-02")
    expected = frames["daily"].loc[start : start + pd.Timedelta(days=6), "prod_gas_mn"].mean()
    assert frames["price_week"].loc[start, "prod_gas_mn"] == pytest.approx(expected)


@pytest.mark.parametrize("method", ["persistence", "seasonal_s4"])
def test_persistence_does_not_measure_long_history(method):
    history = pd.Series(np.arange(80.0), index=np.arange(8000, 8080))
    assert forecast_one(history, 8080, method, None) == forecast_one(history, 8080, method, 40)


def test_financial_grid_covers_approved_orders():
    configs = enumerate_configs()
    methods = {method for method, _window in configs}
    assert ("persistence", None) in configs
    assert ("persistence", 40) in configs
    assert ("seasonal_s4", None) in configs
    assert "ses" in methods
    assert "holt_damped" in methods
    assert "hw_add_damped_s4" in methods
    assert "holt" not in methods
    assert "arima110" not in methods
    orders = arima_orders()
    seasonal = sarima_orders()
    assert set(orders) == {
        (0, 0, 0),
        (1, 0, 0),
        (0, 0, 1),
        (0, 1, 0),
        (1, 1, 0),
        (0, 1, 1),
    }
    assert len(seasonal) == 27
    assert all(p + q <= 1 for p, d, q in orders)
    assert all(d + D <= 1 and P + Q <= 1 for p, d, q, P, D, Q in seasonal)
    assert (1, 0, 1) not in orders
    assert all((p, d, q, 0, 1, 0) not in seasonal for p, d, q in orders if d == 1)
    assert len(configs) == 76


def test_future_target_does_not_change_earlier_baseline_forecast():
    history = pd.Series(np.linspace(10.0, 40.0, 60), index=np.arange(8000, 8060))
    origin = 8050
    hat = forecast_one(history, origin, "arima_1_0_0", 40)
    changed = history.copy()
    changed.loc[origin:] = 999.0
    assert forecast_one(changed, origin, "arima_1_0_0", 40) == pytest.approx(hat)


def _series_with_exposure(n=20, start=8070):
    idx = np.arange(start, start + n)
    y = pd.Series(100.0 + np.arange(n, dtype=float), index=idx)
    x = pd.Series(np.arange(n, dtype=float), index=idx)
    hats = {int(k): 90.0 for k in idx}
    return y, x, hats


def test_residual_uses_locked_baseline_not_last_value():
    y, x, hats = _series_with_exposure()
    eval_keys = [int(y.index[-1])]
    rows = residual_correction(y, x, eval_keys, hats, "sarima_1_0_0_1_0_0_4", None)
    assert rows[0]["status"] == "fitted"
    assert rows[0]["method"] == "sarima_1_0_0_1_0_0_4"
    assert rows[0]["window"] is None
    assert rows[0]["baseline_hat"] == 90.0
    persistence_resid = float(y.iloc[-2] - y.iloc[-3])
    locked_resid = float(y.iloc[-2] - 90.0)
    assert persistence_resid != pytest.approx(locked_resid)
    assert rows[0]["n_pairs"] >= 8
    expected = 90.0 + rows[0]["alpha"] + rows[0]["beta"] * float(x.iloc[-1])
    persist_style = rows[0]["dummy"] + rows[0]["alpha"] + rows[0]["beta"] * float(x.iloc[-1])
    assert rows[0]["hat"] == pytest.approx(expected)
    assert rows[0]["hat"] != pytest.approx(persist_style)


def test_residual_insufficient_history_is_not_a_fitted_correction():
    y, x, hats = _series_with_exposure(n=6)
    eval_keys = [int(y.index[-1])]
    rows = residual_correction(y, x, eval_keys, hats, "persistence", None)
    assert rows[0]["status"] == "insufficient_history"
    assert rows[0]["n_pairs"] < 8
    assert rows[0]["hat"] != rows[0]["hat"]  # NaN
    packed = pack_corr(rows)
    assert packed["n_fitted"] == 0
    assert packed["n_insufficient"] == 1
    assert packed["eval_1Q24_1Q26"].get("n", 0) == 0


def test_future_target_does_not_change_fitted_residual_correction():
    y, x, hats = _series_with_exposure()
    t = int(y.index[-1])
    original = residual_correction(y, x, [t], hats, "ses", 40)[0]
    changed = y.copy()
    changed.loc[t] = y.loc[t] + 1000.0
    hats_changed = dict(hats)
    hats_changed[t] = hats[t] + 50.0
    later = residual_correction(changed, x, [t], hats, "ses", 40)[0]
    assert later["alpha"] == pytest.approx(original["alpha"])
    assert later["beta"] == pytest.approx(original["beta"])
    assert later["hat"] == pytest.approx(original["hat"])
    later_hat_only = residual_correction(y, x, [t], hats_changed, "ses", 40)[0]
    assert later_hat_only["alpha"] == pytest.approx(original["alpha"])
    assert later_hat_only["hat"] != pytest.approx(original["hat"])


def test_residual_metrics_use_identical_fitted_dates():
    y, x, hats = _series_with_exposure()
    eval_keys = [int(k) for k in y.index[-4:]]
    rows = residual_correction(y, x, eval_keys, hats, "holt_damped", None)
    packed = pack_corr(rows)
    fitted = [r for r in packed["points"] if r["status"] == "fitted"]
    score = packed["eval_1Q24_1Q26"]
    assert score["n"] == len(fitted)
    assert score["baseline_RMSE"] == pytest.approx(
        float(np.sqrt(np.mean([(r["actual"] - r["baseline_hat"]) ** 2 for r in fitted])))
    )


def test_two_percent_tie_keeps_equal_error_on_the_boundary():
    simple = {"group": "y_exp0", "family": "ppi_x_vol", "RMSE": 100.0, "complexity": 3}
    complex_ = {"group": "y_exp_l08", "family": "ppi_x_vol", "RMSE": 100.0 / 1.02, "complexity": 11}
    assert matrix._min_rmse([complex_, simple]) == simple
    complex_["RMSE"] = 100.0 / 1.02 - 1e-9
    assert matrix._min_rmse([complex_, simple]) == complex_


def test_sensitivity_table_names_selected_baseline():
    report = {
        "residual_correction": {
            "targets": {
                "lucro bruto RT&M": {
                    "baseline": {"method": "sarima_1_0_0_1_0_0_4", "window": None},
                    "uncorrected": {"eval_1Q24_1Q26": {"RMSE": 10.0, "n": 9}},
                    "corrected": {
                        "prod": {
                            "baseline": {"method": "sarima_1_0_0_1_0_0_4", "window": None},
                            "eval_1Q24_1Q26": {"n": 9, "RMSE": 8.0, "baseline_RMSE": 10.0},
                            "eval_1Q24_4Q25": {"n": 8, "RMSE": 7.0, "baseline_RMSE": 9.0},
                            "legacy_2Q26": {"n": 1, "RMSE": 1.0, "baseline_RMSE": 1.2},
                        }
                    },
                }
            }
        }
    }
    rows = residual_sensitivity_rows(report)
    assert rows
    assert all("RMSE persistência" not in row for row in rows)
    assert all(row["método baseline"] == "sarima_1_0_0_1_0_0_4" for row in rows)
    first = rows[0]
    assert first["RMSE controle"] == 10.0
    assert first["RMSE correção"] == 8.0
    assert first["ganho RMSE %"] == pytest.approx(20.0)
