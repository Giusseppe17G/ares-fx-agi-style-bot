"""Cost fragility checks for fast robustness validation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..backtesting.stress_tester import STRESS_SPREAD_FLOOR_POINTS
from .robustness_runner import metrics_from_values, trade_values


COST_MULTIPLIERS = (1.0, 1.25, 1.5, 2.0, 3.0)
COST_COLUMNS = ("spread_points", "slippage_points", "commission", "lot", "point", "tick_size", "tick_value")
# Fixed penalties of the previous model, in trade_values units. They stay as a
# per-trade floor so a cheap wide-stop trade is never stressed less than before.
LEGACY_PENALTY_FLOOR = {1.0: 0.0, 1.25: 0.0125, 1.5: 0.025, 2.0: 0.05, 3.0: 0.10}
# Same gate as stress_tester: an edge must survive doubled costs to be OK.
GATE_COST_MULTIPLIER = 2.0


def analyze_cost_sensitivity(trades: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    """Measure how quickly edge disappears when each trade's own costs are scaled."""

    values = trade_values(trades)
    # label is the cost units, or the fail-closed reason when costs is None.
    costs, label = _round_trip_costs(trades) if not values.empty else (None, "NO_TRADES")
    if costs is None:
        # Fail closed: without each trade's real costs there is no cost evidence.
        return {
            "mode": "cost-sensitivity",
            "classification": "NEEDS_MORE_ROBUSTNESS_DATA",
            "cost_fragility_score": 100.0,
            "break_even_cost_multiplier": None,
            "reason": label,
            "execution_attempted": False,
        }, pd.DataFrame()
    rows = []
    baseline = metrics_from_values(values.tolist())
    for multiplier in COST_MULTIPLIERS:
        # Each trade already paid its round trip once; k times it adds (k - 1),
        # never less than the legacy fixed penalty for the same multiplier.
        floor = LEGACY_PENALTY_FLOOR[multiplier]
        penalty = np.maximum(costs * (multiplier - 1.0), floor)
        metrics = metrics_from_values((values.to_numpy() - penalty).tolist())
        rows.append({"cost_multiplier": multiplier, "mean_penalty": float(penalty.mean()), "penalty_floor": floor, **metrics})
    frame = pd.DataFrame(rows)
    break_even = None
    for _, row in frame.iterrows():
        if float(row["profit_factor"]) < 1.0 or float(row["expectancy_r"]) <= 0:
            break_even = float(row["cost_multiplier"])
            break
    pf_x2 = float(frame.loc[frame["cost_multiplier"] == GATE_COST_MULTIPLIER, "profit_factor"].iloc[0])
    exp_x2 = float(frame.loc[frame["cost_multiplier"] == GATE_COST_MULTIPLIER, "expectancy_r"].iloc[0])
    pf_drop = max(0.0, float(baseline["profit_factor"]) - pf_x2)
    exp_drop = max(0.0, float(baseline["expectancy_r"]) - exp_x2)
    fragility = min(100.0, pf_drop * 20.0 + exp_drop * 100.0 + (25.0 if break_even is not None and break_even <= 1.5 else 0.0))
    # An edge that is gone at 2x costs is never OK, as in the stress_tester gate.
    gate_failed = pf_x2 < 1.0 or exp_x2 <= 0 or (break_even is not None and break_even <= GATE_COST_MULTIPLIER)
    if gate_failed:
        classification = "NEEDS_COST_RECALIBRATION"
    elif fragility >= 70:
        classification = "COST_FRAGILE"
    else:
        classification = "COST_SENSITIVITY_OK"
    return {
        "mode": "cost-sensitivity",
        "classification": classification,
        "baseline_profit_factor": baseline["profit_factor"],
        "baseline_expectancy_r": baseline["expectancy_r"],
        "profit_factor_cost_x2": pf_x2,
        "expectancy_r_cost_x2": exp_x2,
        "break_even_cost_multiplier": break_even,
        "cost_fragility_score": float(fragility),
        "cost_model": "ROUND_TRIP_SPREAD_PLUS_FLOOR_SLIPPAGE_COMMISSION",
        "penalty_rule": "MAX_SCALED_ROUND_TRIP_OR_LEGACY_FIXED_PENALTY",
        "gate_cost_multiplier": GATE_COST_MULTIPLIER,
        "cost_units": label,
        "spread_floor_points": STRESS_SPREAD_FLOOR_POINTS,
        "execution_attempted": False,
    }, frame


def _round_trip_costs(trades: pd.DataFrame) -> tuple[np.ndarray | None, str]:
    """Each trade's round trip and its units, or None and the fail-closed reason."""

    invalid = "COST_INPUTS_MISSING_OR_INVALID"
    if not {"profit", "r_multiple", *COST_COLUMNS} <= set(trades.columns):
        return None, invalid
    num = {name: pd.to_numeric(trades[name], errors="coerce").astype(float).to_numpy()
        for name in ("profit", "r_multiple", *COST_COLUMNS)}
    if not all(np.isfinite(num[name]).all() for name in COST_COLUMNS):
        return None, invalid
    if any((num[name] < 0).any() for name in ("spread_points", "slippage_points", "commission")):
        return None, invalid
    if any((num[name] <= 0).any() for name in ("lot", "point", "tick_size", "tick_value")):
        return None, invalid
    money_per_point = num["point"] / num["tick_size"] * num["tick_value"] * num["lot"]
    money = (num["spread_points"] + STRESS_SPREAD_FLOOR_POINTS + 2.0 * num["slippage_points"]) * money_per_point + num["commission"]
    # Same unit rule as trade_values: R multiples whenever any of them is nonzero.
    r_multiple = np.where(np.isnan(num["r_multiple"]), 0.0, num["r_multiple"])
    if np.abs(r_multiple).sum() <= 0:
        costs, units = money, "PROFIT"
    elif np.array_equal(np.nan_to_num(num["profit"]), r_multiple):
        # One column was copied from the other (normalize_trade_frame fills a
        # missing profit or r_multiple), so values may be R or money: no units.
        return None, "PROFIT_AND_R_MULTIPLE_NOT_DISTINCT"
    else:
        with np.errstate(divide="ignore", invalid="ignore"):
            risk = np.where((num["profit"] != 0) & (r_multiple != 0), num["profit"] / r_multiple, np.nan)
        if {"entry_price", "initial_sl_price"} <= set(trades.columns):
            distance = np.abs(pd.to_numeric(trades["entry_price"], errors="coerce").to_numpy(dtype=float)
                - pd.to_numeric(trades["initial_sl_price"], errors="coerce").to_numpy(dtype=float))
            risk = np.where(np.isnan(risk), distance / num["tick_size"] * num["tick_value"] * num["lot"], risk)
        if not (np.isfinite(risk) & (risk > 0)).all():
            return None, invalid
        costs, units = money / risk, "R"
    return (costs, units) if np.isfinite(costs).all() else (None, invalid)
