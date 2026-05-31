"""Rejection labeling snapshot for Micro V2 checkpoints."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from agi_style_forex_bot_mt5.forward_sufficiency.rejection_funnel import REJECTION_EVENTS


def build_rejection_snapshot(v2_dataset: Mapping[str, Any], existing_rejection: Mapping[str, Any]) -> dict[str, Any]:
    counter: Counter[str] = Counter()
    for event in v2_dataset.get("events", []):
        event_type = str(event.get("event_type", "")).upper()
        if event_type in REJECTION_EVENTS:
            counter[event_type] += 1
    return {
        "rejection_labeling_status": existing_rejection.get("rejection_labeling_status", ""),
        "symbol_rejected_count": counter.get("SYMBOL_REJECTED", 0),
        "market_closed_rejection_count": counter.get("MARKET_CLOSED_REJECTION", 0),
        "stale_tick_rejection_count": counter.get("STALE_TICK_REJECTION", 0),
        "future_signal_rejection_count": counter.get("FUTURE_SIGNAL_REJECTION", 0),
        "invalid_market_snapshot_rejection_count": counter.get("INVALID_MARKET_SNAPSHOT_REJECTION", 0),
        "total_rejections_seen": sum(counter.values()),
        "new_taxonomy_available": bool(existing_rejection.get("new_taxonomy_available", False)) or any(
            counter.get(name, 0) > 0
            for name in (
                "MARKET_CLOSED_REJECTION",
                "STALE_TICK_REJECTION",
                "FUTURE_SIGNAL_REJECTION",
                "INVALID_MARKET_SNAPSHOT_REJECTION",
            )
        ),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
