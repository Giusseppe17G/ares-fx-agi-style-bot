"""Market-open readiness snapshot for Micro V2 checkpoints."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_market_open_readiness.fresh_tick_audit import audit_fresh_ticks
from agi_style_forex_bot_mt5.micro_v2_market_open_readiness.market_closed_audit import audit_market_closed
from agi_style_forex_bot_mt5.micro_v2_market_open_readiness.mt5_connection_audit import audit_mt5_connection
from agi_style_forex_bot_mt5.micro_v2_market_open_readiness.v2_runtime_state_audit import audit_v2_runtime_state


def build_readiness_snapshot(v2_dataset: Mapping[str, Any], existing_readiness: Mapping[str, Any]) -> dict[str, Any]:
    _rows, tick_summary = audit_fresh_ticks(v2_dataset)
    closed = audit_market_closed(v2_dataset, {})
    mt5 = audit_mt5_connection(v2_dataset)
    runtime = audit_v2_runtime_state(v2_dataset, {})
    return {
        "readiness_status": existing_readiness.get("micro_v2_market_open_readiness_status", ""),
        "v2_runtime_active": runtime.get("v2_runtime_active", False),
        "mt5_connected": mt5.get("mt5_connected", False),
        "fresh_tick_symbols": tick_summary.get("fresh_tick_symbols", []),
        "stale_tick_symbols": tick_summary.get("stale_tick_symbols", []),
        "market_closed_rejection_count": closed.get("market_closed_rejection_count", 0),
        "market_closed_rejection_dominant": closed.get("market_closed_rejection_dominant", False),
        "stale_tick_rejection_count": closed.get("stale_tick_rejection_count", 0),
        "invalid_market_snapshot_rejection_count": closed.get("invalid_market_snapshot_rejection_count", 0),
        "future_signal_rejection_count": closed.get("future_signal_rejection_count", 0),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
