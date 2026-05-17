"""Temporal edge decay scoring."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..robustness_validation.robustness_runner import trade_values


def analyze_temporal_edge_decay(fold_diagnostics: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    """Quantify whether edge disappears in later folds or top trades dominate."""

    if fold_diagnostics.empty:
        return {
            "edge_decay_score": 100.0,
            "overfit_risk_score": 100.0,
            "fold_stability_score": 0.0,
            "latest_folds_negative": False,
            "top_5pct_profit_share": 0.0,
            "classification": "NEEDS_MORE_DATA",
            "execution_attempted": False,
        }
    expectations = pd.to_numeric(fold_diagnostics["expectancy_r"], errors="coerce").fillna(0.0)
    midpoint = max(1, len(expectations) // 2)
    early = float(expectations.iloc[:midpoint].mean())
    late = float(expectations.iloc[midpoint:].mean()) if len(expectations) > midpoint else early
    latest_negative = bool(len(expectations) >= 2 and expectations.iloc[-1] < 0)
    edge_decay = max(0.0, min(100.0, (early - late) * 100.0 + (30.0 if latest_negative else 0.0)))
    profitable_folds = int((expectations > 0).sum())
    fold_stability = float(profitable_folds / len(expectations) * 100.0)
    values = trade_values(trades)
    top_share = _top_profit_share(values)
    overfit = min(100.0, edge_decay * 0.6 + max(0.0, top_share - 0.40) * 100.0)
    return {
        "edge_decay_score": float(edge_decay),
        "overfit_risk_score": float(overfit),
        "fold_stability_score": fold_stability,
        "early_fold_expectancy": early,
        "late_fold_expectancy": late,
        "latest_folds_negative": latest_negative,
        "top_5pct_profit_share": float(top_share),
        "classification": "TEMPORAL_STABLE" if fold_stability >= 67 and not latest_negative else "TEMPORAL_EDGE_DECAY",
        "execution_attempted": False,
    }


def _top_profit_share(values: pd.Series) -> float:
    positives = values[values > 0]
    total = float(positives.sum())
    if total <= 0 or positives.empty:
        return 0.0
    count = max(1, int(len(values) * 0.05))
    return float(positives.sort_values(ascending=False).head(count).sum() / total)
