"""Forward evidence drift summary."""

from __future__ import annotations

from typing import Any, Mapping


def summarize_forward_drift(*, forward_metrics: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    closed = int(forward_metrics.get("closed_trades", 0) or 0)
    if closed < 10:
        return {"mode": "drift-summary", "classification": "INSUFFICIENT_FORWARD_DATA", "reasons": ["fewer than 10 closed paper trades"], "execution_attempted": False}
    reasons: list[str] = []
    if _num(baseline.get("winrate")) - _num(forward_metrics.get("forward_winrate")) >= 20:
        reasons.append("winrate drift")
    if _num(baseline.get("profit_factor")) - _num(forward_metrics.get("forward_profit_factor")) >= 0.5 or _num(forward_metrics.get("forward_profit_factor")) < 1.0:
        reasons.append("profit factor drift")
    if _num(baseline.get("expectancy_r")) - _num(forward_metrics.get("forward_expectancy_r")) >= 0.25 or _num(forward_metrics.get("forward_expectancy_r")) < 0:
        reasons.append("expectancy drift")
    if _num(forward_metrics.get("signal_frequency_per_day")) == 0:
        reasons.append("signal frequency drift")
    if _negative_groups(forward_metrics.get("trades_by_symbol", [])) >= 2:
        reasons.append("symbol drift")
    if _negative_groups(forward_metrics.get("trades_by_strategy", [])) >= 2:
        reasons.append("strategy drift")
    if _negative_groups(forward_metrics.get("trades_by_session", [])) or _negative_groups(forward_metrics.get("trades_by_regime", [])):
        reasons.append("session/regime drift")
    if not reasons:
        classification = "NO_DRIFT"
    elif len(reasons) >= 3 or _num(forward_metrics.get("forward_expectancy_r")) < 0:
        classification = "CRITICAL_DRIFT"
    else:
        classification = "WATCHLIST_DRIFT"
    return {"mode": "drift-summary", "classification": classification, "reasons": reasons or ["forward aligned"], "execution_attempted": False}


def _negative_groups(rows: Any) -> int:
    if not isinstance(rows, list):
        return 0
    return sum(1 for row in rows if _num(row.get("expectancy_r")) < 0)


def _num(value: Any) -> float:
    try:
        if value in {None, ""}:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
