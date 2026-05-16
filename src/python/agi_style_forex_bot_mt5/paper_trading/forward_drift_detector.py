"""Forward-vs-research drift detection."""

from __future__ import annotations

from typing import Any, Mapping


def detect_forward_drift(
    *,
    forward: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    if int(forward.get("closed_trades", 0) or 0) < 30:
        return {"classification": "NEEDS_MORE_DATA", "reasons": ["insufficient forward trades"]}
    if float(forward.get("expectancy_r", 0.0) or 0.0) < float(baseline.get("expectancy_r", 0.0) or 0.0) - 0.2:
        reasons.append("expectancy drift")
    if float(forward.get("winrate", 0.0) or 0.0) < float(baseline.get("winrate", 0.0) or 0.0) - 15:
        reasons.append("winrate drift")
    if float(forward.get("average_spread", 0.0) or 0.0) > float(baseline.get("spread_p95", 999.0) or 999.0):
        reasons.append("cost drift")
    if abs(float(forward.get("max_drawdown_shadow", 0.0) or 0.0)) > abs(float(baseline.get("max_drawdown_pct", 999.0) or 999.0)) * 1.5:
        reasons.append("drawdown drift")
    if "cost drift" in reasons:
        classification = "COST_DRIFT"
    elif reasons:
        classification = "PERFORMANCE_DRIFT"
    else:
        classification = "FORWARD_OK"
    if classification != "FORWARD_OK" and float(forward.get("expectancy_r", 0.0) or 0.0) < 0:
        classification = "REJECT_STRATEGY"
    return {"classification": classification, "reasons": reasons or ["forward aligned with baseline"]}
