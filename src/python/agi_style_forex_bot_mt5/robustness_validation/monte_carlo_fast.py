"""Fast Monte Carlo over existing BALANCED trades."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .robustness_runner import metrics_from_values, trade_values


def run_monte_carlo_fast(
    trades: pd.DataFrame,
    *,
    simulations: int = 1000,
    seed: int = 0,
    ruin_threshold_r: float = 10.0,
    metrics_only: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Bootstrap trade values and return distribution summary."""

    values = trade_values(trades).to_numpy(dtype=float)
    if len(values) == 0:
        limited = dict(metrics_only or {})
        return {
            "mode": "monte-carlo-fast",
            "classification": "LIMITED_MONTE_CARLO" if limited else "NEEDS_MORE_ROBUSTNESS_DATA",
            "simulations": 0,
            "seed": seed,
            "total_trades": int(limited.get("trades_generated", limited.get("total_trades", 0)) or 0),
            "median_return": None,
            "p05_return": None,
            "p95_return": None,
            "max_drawdown_p95": None,
            "losing_streak_p95": None,
            "risk_of_ruin": None,
            "probability_profit_positive": None,
            "execution_attempted": False,
        }, pd.DataFrame()
    rng = np.random.default_rng(seed)
    rows: list[dict[str, float]] = []
    for index in range(simulations):
        sample = rng.choice(values, size=len(values), replace=True)
        cumulative = np.cumsum(sample)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max
        rows.append(
            {
                "simulation": float(index),
                "final_return": float(cumulative[-1]),
                "max_drawdown": float(drawdown.min()),
                "longest_losing_streak": float(_longest_losing_streak(sample)),
            }
        )
    frame = pd.DataFrame(rows)
    classification = "MONTE_CARLO_OK" if float((frame["final_return"] > 0).mean()) >= 0.60 else "MONTE_CARLO_WARNING"
    summary = {
        "mode": "monte-carlo-fast",
        "classification": classification,
        "simulations": simulations,
        "seed": seed,
        "total_trades": len(values),
        "median_return": float(frame["final_return"].median()),
        "p05_return": float(frame["final_return"].quantile(0.05)),
        "p95_return": float(frame["final_return"].quantile(0.95)),
        "max_drawdown_p95": float(frame["max_drawdown"].quantile(0.05)),
        "losing_streak_p95": float(frame["longest_losing_streak"].quantile(0.95)),
        "risk_of_ruin": float((frame["max_drawdown"] <= -abs(ruin_threshold_r)).mean()),
        "probability_profit_positive": float((frame["final_return"] > 0).mean()),
        "baseline_metrics": metrics_from_values(values),
        "execution_attempted": False,
    }
    return summary, frame


def _longest_losing_streak(values: np.ndarray) -> int:
    best = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best
