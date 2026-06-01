"""Market stability audit for Micro V2."""

from __future__ import annotations

from typing import Any, Mapping


def audit_market_stability(filter_analysis: Mapping[str, Any], checkpoint: Mapping[str, Any], readiness: Mapping[str, Any]) -> dict[str, Any]:
    total = int(filter_analysis.get("total_v2_rejections", checkpoint.get("v2_signals_rejected", 0)) or 0)
    market_closed = int(filter_analysis.get("market_closed_rejection_count", checkpoint.get("market_closed_rejection_count", 0)) or 0)
    stale = int(filter_analysis.get("stale_tick_rejection_count", checkpoint.get("stale_tick_rejection_count", 0)) or 0)
    fresh = _list(filter_analysis.get("fresh_tick_symbols") or checkpoint.get("fresh_tick_symbols") or readiness.get("fresh_tick_symbols"))
    stale_symbols = _list(filter_analysis.get("stale_tick_symbols") or checkpoint.get("stale_tick_symbols") or readiness.get("stale_tick_symbols"))
    ratio = round(market_closed / total, 4) if total else 0.0
    status = "MARKET_STABLE_ENOUGH_FOR_FILTER_ANALYSIS"
    if ratio > 0.5:
        status = "MARKET_CLOSED_DOMINATES"
    elif not fresh:
        status = "FRESH_TICK_DATA_MISSING"
    elif len(fresh) == 1 and stale_symbols:
        status = "PARTIAL_FRESH_TICK_COVERAGE"
    return {
        "market_stability_status": status,
        "market_closed_rejection_count": market_closed,
        "stale_tick_rejection_count": stale,
        "total_rejections": total,
        "market_closed_dominance_ratio": ratio,
        "fresh_tick_symbols": fresh,
        "stale_tick_symbols": stale_symbols,
        "fresh_tick_symbol_count": len(fresh),
        "signals_detected": int(filter_analysis.get("total_v2_signals", checkpoint.get("v2_signals_detected", 0)) or 0),
        "signals_rejected": total,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).upper() for item in value if str(item)]
    if isinstance(value, str) and value:
        return [item.strip().upper() for item in value.split(",") if item.strip()]
    return []
