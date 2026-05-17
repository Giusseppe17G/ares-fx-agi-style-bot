"""Session and regime stability recommendations."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..robustness_validation.robustness_runner import metrics_from_values, trade_values


def analyze_regime_session_stability(trades: pd.DataFrame) -> dict[str, Any]:
    """Return stable allow/block lists for sessions and regimes."""

    sessions = _group_stability(trades, "session")
    regimes = _group_stability(trades, "regime")
    return {
        "sessions": sessions.to_dict("records"),
        "regimes": regimes.to_dict("records"),
        "allowed_sessions_stable": _names(sessions, "session", "STABLE_KEEP"),
        "blocked_sessions_stable": _names(sessions, "session", "DISABLE_FOR_NOW"),
        "allowed_regimes_stable": _names(regimes, "regime", "STABLE_KEEP"),
        "blocked_regimes_stable": _names(regimes, "regime", "DISABLE_FOR_NOW"),
        "execution_attempted": False,
    }


def _group_stability(trades: pd.DataFrame, column: str) -> pd.DataFrame:
    if trades.empty or column not in trades.columns:
        return pd.DataFrame(columns=[column, "trades", "profit_factor", "expectancy_r", "decision"])
    rows = []
    for value, group in trades.groupby(column):
        metrics = metrics_from_values(trade_values(group).tolist())
        decision = "WATCHLIST"
        if str(value).upper() == "ROLLOVER" and (metrics["expectancy_r"] < 0 or metrics["profit_factor"] < 1.05):
            decision = "DISABLE_FOR_NOW"
        elif metrics["total_trades"] >= 20 and metrics["expectancy_r"] >= 0 and metrics["profit_factor"] >= 1.0:
            decision = "STABLE_KEEP"
        elif metrics["total_trades"] >= 20 and (metrics["expectancy_r"] < 0 or metrics["profit_factor"] < 1.0):
            decision = "DISABLE_FOR_NOW"
        rows.append({column: value, "trades": metrics["total_trades"], "profit_factor": metrics["profit_factor"], "expectancy_r": metrics["expectancy_r"], "decision": decision})
    return pd.DataFrame(rows)


def _names(frame: pd.DataFrame, column: str, decision: str) -> list[str]:
    if frame.empty:
        return []
    return [str(value) for value in frame.loc[frame["decision"] == decision, column].dropna().tolist()]
