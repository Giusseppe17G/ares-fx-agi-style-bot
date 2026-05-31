"""Fresh/stale tick scope for Micro V2 filter analysis."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_market_open_readiness.fresh_tick_audit import audit_fresh_ticks


def build_fresh_tick_scope(dataset: Mapping[str, Any], readiness: Mapping[str, Any], checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    _rows, tick_summary = audit_fresh_ticks(dataset)
    fresh = list(tick_summary.get("fresh_tick_symbols") or readiness.get("fresh_tick_symbols") or checkpoint.get("fresh_tick_symbols") or [])
    stale = list(tick_summary.get("stale_tick_symbols") or readiness.get("stale_tick_symbols") or checkpoint.get("stale_tick_symbols") or [])
    return {
        "fresh_tick_symbols": sorted({str(symbol).upper() for symbol in fresh if symbol}),
        "stale_tick_symbols": sorted({str(symbol).upper() for symbol in stale if symbol}),
        "symbols_with_tick_evidence": tick_summary.get("symbols_with_tick_evidence", []),
        "fresh_tick_data_available": bool(fresh),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
