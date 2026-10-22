"""Cost stress scales the whole round trip in the trade's own units.

A recorded spread of zero is valid (PROJECT_SPEC.md), so every cost stress adds
a spread floor on top of the recorded spread; commission and slippage on both
sides are scaled by the same multiplier.
"""

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting.stress_tester import StressTester, run_stress_report
from agi_style_forex_bot_mt5.robustness_validation import analyze_cost_sensitivity, run_robustness_fast
from agi_style_forex_bot_mt5.robustness_validation.robustness_runner import normalize_trade_frame
from test_backtesting import _trade


# Documented additive floor, in instrument points; lowering it weakens the stress.
SPREAD_FLOOR_POINTS = 10.0
# Fixed penalties of the previous model, kept as a per-trade floor in the units
# trade_values uses; lowering them would stress a cheap trade less than before.
LEGACY_PENALTY = {1.0: 0.0, 1.25: 0.0125, 1.5: 0.025, 2.0: 0.05, 3.0: 0.10}


def _priced_trade(*, spread_points: float, commission: float = 3.0):
    # 0.2 lot at 0.4 USD per point per lot: 0.08 USD per point; 1R = 50 USD.
    return replace(_trade(100), lot=0.2, spread_points=spread_points, slippage_points=1,
        point=0.00001, tick_size=0.00005, tick_value=2, r_multiple=2, commission=commission)


@pytest.mark.parametrize("spread_points", [10.0, 0.0])
@pytest.mark.parametrize("multiplier", [1.0, 1.5, 2.0, 3.0])
def test_cost_multiplier_scales_spread_floor_slippage_and_commission(spread_points, multiplier):
    rows = StressTester().comprehensive([_priced_trade(spread_points=spread_points)])
    result = next(r for r in rows if r.scenario == "cost_multiplier" and r.parameters["cost_multiplier"] == multiplier)
    round_trip = (spread_points + SPREAD_FLOOR_POINTS + 2 * 1) * 0.08 + 3.0
    expected = 100 - (multiplier - 1.0) * round_trip
    assert result.status == "COMPLETED"
    assert result.metrics.net_profit == pytest.approx(expected)
    assert result.metrics.average_r == pytest.approx(expected / 50)


def test_spread_stress_still_bites_when_recorded_spread_is_zero():
    trade = _priced_trade(spread_points=0.0)
    result = StressTester().spread_slippage_sensitivity([trade], spread_multipliers=(2,), extra_slippage_points=(0,))[0]
    # Old behaviour: 0 * (2 - 1) = 0 extra points, so the stress was a no-op.
    assert result.metrics.net_profit == pytest.approx(100 - SPREAD_FLOOR_POINTS * 0.08)


def _zero_spread_book(count: int = 40):
    # 5-digit EURUSD, 0.1 lot, 100-point SL: 1R = 10 USD and 1 point = 0.1 USD.
    # Round trip at 2x adds (0 + floor + 2 * 1 slip) points and 0.7 USD commission.
    start = pd.Timestamp("2026-01-05T00:00:00Z")
    trades = []
    for index in range(count):
        profit = 4.0 if index % 2 == 0 else -3.0
        trades.append(replace(_trade(profit, signal_id=f"z{index}"), lot=0.1, point=0.00001,
            tick_size=0.00001, tick_value=1.0, spread_points=0.0, slippage_points=1.0,
            commission=0.7, r_multiple=profit / 10.0,
            entry_time=(start + pd.Timedelta(hours=index)).isoformat(),
            exit_time=(start + pd.Timedelta(hours=index, minutes=30)).isoformat()))
    return trades


def test_zero_spread_book_cannot_pass_the_2x_cost_gate(tmp_path):
    # +0.5 USD per trade gross edge; doubling the real 1.9 USD round trip makes it negative.
    report = run_stress_report(trades=_zero_spread_book(), report_dir=tmp_path)
    rows = pd.read_csv(tmp_path / "scenarios.csv")
    x2 = rows.loc[(rows.scenario == "cost_multiplier") & rows.parameters.str.contains('"cost_multiplier": 2.0')]
    assert report["classification"] != "APPROVED_FOR_SHADOW_OBSERVATION"
    assert report["classification"] == "WATCHLIST"
    assert float(x2.net_profit.iloc[0]) == pytest.approx(40 * 0.5 - 40 * ((SPREAD_FLOOR_POINTS + 2) * 0.1 + 0.7))
    assert report["effective_config"]["cost_assumptions"]["spread_floor_points"] == SPREAD_FLOOR_POINTS


def _cost_frame(count: int, win_r: float, loss_r: float, *, sl_points: float = 100.0, lot: float = 0.1,
        spread: float = 0.0, slippage: float = 1.0, commission: float = 0.7) -> pd.DataFrame:
    # 5 digits at 1 USD per point per lot. Defaults: 0.1 lot, 100-point SL, so
    # 1R = 10 USD and 1 point = 0.1 USD.
    risk = sl_points * lot
    rows = []
    for index in range(count):
        r = win_r if index % 2 == 0 else -loss_r
        rows.append({
            "signal_id": f"c{index}", "symbol": "EURUSD", "strategy_name": "strategy_ensemble",
            "session": "LONDON", "regime": "TREND_UP",
            "entry_time": f"2024-01-{(index % 28) + 1:02d}T00:00:00Z",
            "exit_time": f"2024-01-{(index % 28) + 1:02d}T01:00:00Z",
            "profit": r * risk, "r_multiple": r, "lot": lot, "point": 0.00001,
            "tick_size": 0.00001, "tick_value": 1.0, "spread_points": spread,
            "slippage_points": slippage, "commission": commission,
            "entry_price": 1.10000, "initial_sl_price": round(1.10000 - sl_points * 0.00001, 5),
        })
    return pd.DataFrame(rows)


def test_cost_sensitivity_uses_each_trades_real_round_trip_cost():
    # Real round trip incl. floor: (0 + 10 + 2) * 0.1 + 0.7 = 1.9 USD = 0.19R per trade.
    # The old fixed 0.05R "2x spread" penalty left this 0.08R edge looking robust.
    summary, frame = analyze_cost_sensitivity(_cost_frame(120, 0.48, 0.32))
    assert summary["classification"] == "NEEDS_COST_RECALIBRATION"
    assert summary["break_even_cost_multiplier"] == 1.5
    assert summary["expectancy_r_cost_x2"] == pytest.approx(0.08 - 0.19)
    assert summary["spread_floor_points"] == SPREAD_FLOOR_POINTS
    x2 = frame.loc[frame["cost_multiplier"] == 2.0].iloc[0]
    assert x2["mean_penalty"] == pytest.approx(0.19)
    assert summary["execution_attempted"] is False


def test_cost_sensitivity_penalizes_in_money_when_values_are_money():
    frame = _cost_frame(120, 0.48, 0.32)
    frame["r_multiple"] = 0.0  # trade_values falls back to profit (USD).
    summary, scenarios = analyze_cost_sensitivity(frame)
    assert summary["cost_units"] == "PROFIT"
    assert scenarios.loc[scenarios["cost_multiplier"] == 2.0, "mean_penalty"].iloc[0] == pytest.approx(1.9)


def test_cost_sensitivity_fails_closed_without_cost_inputs():
    frame = _cost_frame(120, 0.75, 0.25).drop(columns=["spread_points", "commission"])
    summary, scenarios = analyze_cost_sensitivity(frame)
    assert summary["classification"] == "NEEDS_MORE_ROBUSTNESS_DATA"
    assert summary["cost_fragility_score"] == 100.0
    assert summary["break_even_cost_multiplier"] is None
    assert scenarios.empty


@pytest.mark.parametrize("column,value", [
    ("spread_points", np.nan), ("spread_points", -1.0), ("commission", -0.5),
    ("slippage_points", np.inf), ("lot", 0.0), ("tick_size", 0.0), ("tick_value", "bad"),
])
def test_cost_sensitivity_fails_closed_on_invalid_cost_inputs(column, value):
    frame = _cost_frame(120, 0.75, 0.25)
    frame[column] = frame[column].astype(object)
    frame.loc[3, column] = value
    summary, scenarios = analyze_cost_sensitivity(frame)
    assert summary["classification"] == "NEEDS_MORE_ROBUSTNESS_DATA"
    assert summary["cost_fragility_score"] == 100.0
    assert scenarios.empty


def test_cost_sensitivity_fails_closed_without_r_denominator():
    frame = _cost_frame(120, 0.75, 0.25).drop(columns=["entry_price", "initial_sl_price"])
    frame.loc[5, ["profit", "r_multiple"]] = 0.0  # Breakeven trade: profit / r is undefined.
    summary, scenarios = analyze_cost_sensitivity(frame)
    assert summary["classification"] == "NEEDS_MORE_ROBUSTNESS_DATA"
    assert scenarios.empty


def test_wide_stop_thin_edge_is_never_stressed_less_than_the_legacy_penalties():
    # 1 lot, 1000-point SL: 1R = 1000 USD. Real round trip (10 + 10 + 2) * 1 + 7 USD
    # = 0.029R, below the legacy 0.05R "2x" penalty. Scaling it alone left a 2x
    # expectancy of -0.004R labelled COST_SENSITIVITY_OK.
    frame = _cost_frame(120, 0.30, 0.25, sl_points=1000.0, lot=1.0, spread=10.0, commission=7.0)
    summary, scenarios = analyze_cost_sensitivity(frame)
    assert summary["classification"] == "NEEDS_COST_RECALIBRATION"
    assert summary["break_even_cost_multiplier"] == 1.5
    assert summary["expectancy_r_cost_x2"] == pytest.approx(0.025 - LEGACY_PENALTY[2.0])
    assert summary["cost_units"] == "R"
    for multiplier, legacy in LEGACY_PENALTY.items():
        row = scenarios.loc[scenarios["cost_multiplier"] == multiplier].iloc[0]
        assert row["mean_penalty"] >= legacy
        assert row["mean_penalty"] == pytest.approx(max((multiplier - 1.0) * 0.029, legacy))
        assert row["penalty_floor"] == legacy


def test_cost_sensitivity_is_never_ok_when_the_edge_is_gone_at_2x_costs():
    # 0.1 lot, 200-point SL: 1R = 20 USD. Round trip (0 + 10 + 2) * 0.1 = 1.2 USD
    # = 0.06R, above every legacy floor. The 0.05R edge survives 1.5x costs but not
    # 2x, and the fragility score alone (about 12) used to call this OK.
    summary, _ = analyze_cost_sensitivity(_cost_frame(120, 0.50, 0.40, sl_points=200.0, commission=0.0))
    assert summary["break_even_cost_multiplier"] == 2.0
    assert summary["expectancy_r_cost_x2"] == pytest.approx(0.05 - 0.06)
    assert summary["profit_factor_cost_x2"] < 1.0
    assert summary["cost_fragility_score"] < 70
    assert summary["classification"] == "NEEDS_COST_RECALIBRATION"
    assert summary["gate_cost_multiplier"] == 2.0


def test_cost_sensitivity_stays_ok_when_the_edge_survives_2x_costs():
    # 0.25R edge against a 0.19R round trip: still positive with doubled costs.
    summary, _ = analyze_cost_sensitivity(_cost_frame(120, 0.75, 0.25))
    assert summary["expectancy_r_cost_x2"] == pytest.approx(0.25 - 0.19)
    assert summary["profit_factor_cost_x2"] >= 1.0
    assert summary["classification"] == "COST_SENSITIVITY_OK"


def test_normalize_trade_frame_keeps_blank_cost_cells_missing():
    frame = pd.DataFrame({"profit": [10.0, None], "r_multiple": [1.0, None],
        "spread_points": [None, "3"], "slippage_points": ["", 1.0], "commission": [0.7, "n/a"]})
    normalized = normalize_trade_frame(frame)
    assert normalized["profit"].tolist() == [10.0, 0.0]
    assert normalized["r_multiple"].tolist() == [1.0, 0.0]
    assert normalized["spread_points"].isna().tolist() == [True, False]
    assert normalized["slippage_points"].isna().tolist() == [True, False]
    assert normalized["commission"].isna().tolist() == [False, True]


@pytest.mark.parametrize("missing", ["profit", "r_multiple"])
def test_cost_sensitivity_fails_closed_when_profit_and_r_multiple_are_copies(missing):
    # normalize_trade_frame copies the present column into the missing one, so the
    # values may be R or money and money costs cannot be put in their units.
    frame = normalize_trade_frame(_cost_frame(120, 0.75, 0.25).drop(columns=[missing]))
    summary, scenarios = analyze_cost_sensitivity(frame)
    assert summary["classification"] == "NEEDS_MORE_ROBUSTNESS_DATA"
    assert summary["cost_fragility_score"] == 100.0
    assert summary["reason"] == "PROFIT_AND_R_MULTIPLE_NOT_DISTINCT"
    assert scenarios.empty


def _run_fast(tmp_path, frame: pd.DataFrame) -> tuple[dict, dict]:
    profile_dir = tmp_path / "profile_runs" / "balanced"
    profile_dir.mkdir(parents=True)
    frame.to_csv(profile_dir / "trades.csv", index=False)
    summary = run_robustness_fast(runs_root=tmp_path / "runs", profile_runs_dir=tmp_path / "profile_runs",
        output_dir=tmp_path / "robustness", simulations=100, seed=7)
    cost = json.loads((tmp_path / "robustness" / "cost_sensitivity.json").read_text(encoding="utf-8"))
    return summary, cost


def test_robustness_fast_with_recorded_costs_sees_cost_fragility(tmp_path):
    # Control for the blank-cell case: (12 + 10 + 2) * 0.1 + 0.7 = 3.1 USD = 0.31R.
    summary, cost = _run_fast(tmp_path, _cost_frame(120, 0.60, 0.30, spread=12.0))
    assert cost["classification"] == "NEEDS_COST_RECALIBRATION"
    assert summary["robustness_decision"] != "PAPER_FORWARD_SHADOW_CANDIDATE"


@pytest.mark.parametrize("columns,rows", [
    (("spread_points", "slippage_points", "commission"), slice(None)),
    (("spread_points", "commission"), slice(None)),
    (("commission",), [7]),
])
def test_robustness_fast_fails_closed_on_blank_cost_cells_end_to_end(tmp_path, columns, rows):
    # Blank cells used to be zero-filled by the loader, so free trades read as
    # COST_SENSITIVITY_OK (break-even 3.0) on the production path.
    frame = _cost_frame(120, 0.60, 0.30, spread=12.0)
    for column in columns:
        frame[column] = frame[column].astype(object)
        frame.loc[rows, column] = ""
    summary, cost = _run_fast(tmp_path, frame)
    assert cost["classification"] == "NEEDS_MORE_ROBUSTNESS_DATA"
    assert cost["cost_fragility_score"] == 100.0
    assert cost["reason"] == "COST_INPUTS_MISSING_OR_INVALID"
    assert cost["break_even_cost_multiplier"] is None
    assert summary["cost_sensitivity_classification"] == "NEEDS_MORE_ROBUSTNESS_DATA"
    assert summary["robustness_decision"] != "PAPER_FORWARD_SHADOW_CANDIDATE"
    assert summary["execution_attempted"] is False
