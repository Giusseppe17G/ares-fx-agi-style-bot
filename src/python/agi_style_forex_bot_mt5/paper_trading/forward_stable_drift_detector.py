"""Drift detector for BALANCED_STABLE forward-shadow observation."""

from __future__ import annotations

from typing import Any, Mapping


def detect_stable_forward_drift(*, forward: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Compare live paper metrics with stable backtest/robustness baselines."""

    closed = int(_number(forward.get("closed_trades")) or _number(forward.get("paper_total_trades")) or 0)
    reasons: list[str] = []
    if closed < 30:
        return {
            "classification": "WATCHLIST_DRIFT",
            "stable_drift_status": "WATCHLIST_DRIFT",
            "reasons": ["insufficient stable forward trades"],
            "execution_attempted": False,
        }
    winrate_drop = _number(baseline.get("winrate"), 0.0) - _number(forward.get("winrate"), 0.0)
    expectancy_drop = _number(baseline.get("expectancy_r"), 0.0) - _number(forward.get("expectancy_r"), 0.0)
    pf_drop = _number(baseline.get("profit_factor"), 0.0) - _number(forward.get("profit_factor"), 0.0)
    rejection_drift = _number(forward.get("rejection_rate"), 0.0) - _number(baseline.get("rejection_rate"), 0.0)
    spread_drift = _number(forward.get("average_spread"), 0.0) - _number(baseline.get("spread_p95"), 999.0)
    if winrate_drop >= 20:
        reasons.append("winrate drift")
    if expectancy_drop >= 0.25 or _number(forward.get("expectancy_r"), 0.0) < 0:
        reasons.append("expectancy drift")
    if pf_drop >= 0.5 or _number(forward.get("profit_factor"), 0.0) < 1.0:
        reasons.append("profit factor drift")
    if rejection_drift >= 25:
        reasons.append("rejection rate drift")
    if spread_drift > 0:
        reasons.append("spread drift")
    if _number(forward.get("symbol_negative_count"), 0.0) >= 2:
        reasons.append("symbol drift")
    if _number(forward.get("strategy_negative_count"), 0.0) >= 2:
        reasons.append("strategy drift")
    if _number(forward.get("session_regime_negative_count"), 0.0) >= 2:
        reasons.append("session/regime drift")
    if not reasons:
        classification = "STABLE_FORWARD_OK"
    elif _number(forward.get("expectancy_r"), 0.0) < 0 or len(reasons) >= 4:
        classification = "CRITICAL_DRIFT"
    else:
        classification = "WATCHLIST_DRIFT"
    if classification == "CRITICAL_DRIFT" and _number(forward.get("profit_factor"), 0.0) < 0.8:
        classification = "PAUSE_STABLE_SHADOW"
    return {
        "classification": classification,
        "stable_drift_status": classification,
        "reasons": reasons or ["stable forward aligned with baseline"],
        "closed_trades": closed,
        "execution_attempted": False,
    }


def _number(value: Any, default: float | None = None) -> float:
    try:
        if value in {None, ""}:
            return 0.0 if default is None else float(default)
        return float(value)
    except (TypeError, ValueError):
        return 0.0 if default is None else float(default)
