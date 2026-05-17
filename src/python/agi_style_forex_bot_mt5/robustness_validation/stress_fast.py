"""Fast deterministic stress tests for existing trade sequences."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .robustness_runner import metrics_from_values, trade_values


def run_stress_fast(trades: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    """Apply cost and concentration shocks to trade R/profit values."""

    values = trade_values(trades)
    if values.empty:
        return {
            "mode": "stress-fast",
            "classification": "NEEDS_MORE_ROBUSTNESS_DATA",
            "stress_passed": False,
            "worst_case_profit_factor": None,
            "worst_case_expectancy_r": None,
            "scenarios_failed": ["NO_TRADES"],
            "most_sensitive_cost": "NO_TRADES",
            "execution_attempted": False,
        }, pd.DataFrame()
    scenarios = {
        "spread_x1_25": values - 0.0125,
        "spread_x1_5": values - 0.025,
        "spread_x2": values - 0.05,
        "slippage_x1_5": values - 0.02,
        "slippage_x2": values - 0.04,
        "commission_increase": values - 0.02,
        "remove_best_5pct": _remove_best(values, 5),
        "remove_best_10pct": _remove_best(values, 10),
        "rollover_exclusion": _exclude(trades, values, "session", "ROLLOVER"),
        "worst_session_exclusion": _exclude_worst_group(trades, values, "session"),
    }
    rows = []
    for scenario, scenario_values in scenarios.items():
        metrics = metrics_from_values(scenario_values.tolist())
        rows.append({"scenario": scenario, **metrics, "failed": bool(metrics["profit_factor"] < 1.0 or metrics["expectancy_r"] <= 0)})
    frame = pd.DataFrame(rows)
    failed = frame.loc[frame["failed"], "scenario"].astype(str).tolist()
    worst = frame.sort_values(["profit_factor", "expectancy_r"], ascending=[True, True]).iloc[0]
    summary = {
        "mode": "stress-fast",
        "classification": "STRESS_OK" if not failed else ("STRESS_WARNING" if len(failed) <= 2 else "STRESS_FAILED"),
        "stress_passed": not failed,
        "worst_case_profit_factor": float(worst["profit_factor"]),
        "worst_case_expectancy_r": float(worst["expectancy_r"]),
        "scenarios_failed": failed,
        "most_sensitive_cost": str(worst["scenario"]),
        "execution_attempted": False,
    }
    return summary, frame


def _remove_best(values: pd.Series, pct: int) -> pd.Series:
    if values.empty:
        return values
    count = max(1, int(len(values) * pct / 100.0))
    drop_index = values.sort_values(ascending=False).head(count).index
    return values.drop(drop_index)


def _exclude(trades: pd.DataFrame, values: pd.Series, column: str, value: str) -> pd.Series:
    if column not in trades.columns:
        return values
    mask = trades[column].astype(str).str.upper() != value
    filtered = values.loc[mask]
    return filtered if not filtered.empty else values


def _exclude_worst_group(trades: pd.DataFrame, values: pd.Series, column: str) -> pd.Series:
    if column not in trades.columns:
        return values
    joined = pd.DataFrame({"value": values, column: trades[column].astype(str).values})
    grouped = joined.groupby(column)["value"].mean().sort_values()
    if grouped.empty:
        return values
    return joined.loc[joined[column] != grouped.index[0], "value"]
