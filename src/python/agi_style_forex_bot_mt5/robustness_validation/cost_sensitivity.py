"""Cost fragility checks for fast robustness validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .robustness_runner import metrics_from_values, trade_values


def analyze_cost_sensitivity(trades: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    """Measure how quickly edge disappears under conservative cost shocks."""

    values = trade_values(trades)
    if values.empty:
        return {
            "mode": "cost-sensitivity",
            "classification": "NEEDS_MORE_ROBUSTNESS_DATA",
            "cost_fragility_score": 100.0,
            "break_even_spread_multiplier": None,
            "execution_attempted": False,
        }, pd.DataFrame()
    rows = []
    baseline = metrics_from_values(values.tolist())
    for multiplier, penalty in ((1.0, 0.0), (1.25, 0.0125), (1.5, 0.025), (2.0, 0.05), (3.0, 0.10)):
        metrics = metrics_from_values((values - penalty).tolist())
        rows.append({"spread_multiplier": multiplier, "penalty_r": penalty, **metrics})
    frame = pd.DataFrame(rows)
    break_even = None
    for _, row in frame.iterrows():
        if float(row["profit_factor"]) < 1.0 or float(row["expectancy_r"]) <= 0:
            break_even = float(row["spread_multiplier"])
            break
    pf_x2 = float(frame.loc[frame["spread_multiplier"] == 2.0, "profit_factor"].iloc[0])
    exp_x2 = float(frame.loc[frame["spread_multiplier"] == 2.0, "expectancy_r"].iloc[0])
    pf_drop = max(0.0, float(baseline["profit_factor"]) - pf_x2)
    exp_drop = max(0.0, float(baseline["expectancy_r"]) - exp_x2)
    fragility = min(100.0, pf_drop * 20.0 + exp_drop * 100.0 + (25.0 if break_even is not None and break_even <= 1.5 else 0.0))
    if break_even is not None and break_even <= 1.5:
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
        "profit_factor_spread_x2": pf_x2,
        "expectancy_r_spread_x2": exp_x2,
        "break_even_spread_multiplier": break_even,
        "cost_fragility_score": float(fragility),
        "execution_attempted": False,
    }, frame
