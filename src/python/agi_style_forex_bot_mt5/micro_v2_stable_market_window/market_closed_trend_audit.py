"""Market-closed dominance trend audit."""

from __future__ import annotations

from typing import Any, Mapping


def audit_market_closed_trend(filter_analysis: Mapping[str, Any], checkpoint: Mapping[str, Any], consolidated: Mapping[str, Any]) -> dict[str, Any]:
    total = int(filter_analysis.get("total_v2_rejections", checkpoint.get("v2_signals_rejected", 0)) or 0)
    market_closed = int(filter_analysis.get("market_closed_rejection_count", checkpoint.get("market_closed_rejection_count", 0)) or 0)
    stale = int(filter_analysis.get("stale_tick_rejection_count", checkpoint.get("stale_tick_rejection_count", 0)) or 0)
    ratio = round(market_closed / total, 4) if total else float(consolidated.get("market_closed_dominance_ratio", 0.0) or 0.0)
    previous_ratio = float(consolidated.get("market_closed_dominance_ratio", ratio) or ratio)
    trend = "FLAT"
    if ratio < previous_ratio:
        trend = "IMPROVING"
    elif ratio > previous_ratio:
        trend = "WORSENING"
    return {
        "market_closed_rejection_count": market_closed,
        "stale_tick_rejection_count": stale,
        "total_rejections": total,
        "market_closed_dominance_ratio": ratio,
        "previous_market_closed_dominance_ratio": round(previous_ratio, 4),
        "market_closed_trend": trend,
        "market_closed_dominates": ratio > 0.5,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
