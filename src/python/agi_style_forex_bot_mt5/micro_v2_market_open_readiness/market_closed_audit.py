"""Market-closed and market-data rejection counters."""

from __future__ import annotations

from typing import Any, Mapping


def audit_market_closed(dataset: Mapping[str, Any], rejection_labeling: Mapping[str, Any]) -> dict[str, Any]:
    counts = {
        "market_closed_rejection_count": 0,
        "stale_tick_rejection_count": 0,
        "future_signal_rejection_count": 0,
        "invalid_market_snapshot_rejection_count": 0,
    }
    for event in dataset.get("events", []):
        event_type = str(event.get("event_type", "")).upper()
        if event_type == "MARKET_CLOSED_REJECTION":
            counts["market_closed_rejection_count"] += 1
        elif event_type == "STALE_TICK_REJECTION":
            counts["stale_tick_rejection_count"] += 1
        elif event_type == "FUTURE_SIGNAL_REJECTION":
            counts["future_signal_rejection_count"] += 1
        elif event_type == "INVALID_MARKET_SNAPSHOT_REJECTION":
            counts["invalid_market_snapshot_rejection_count"] += 1
    for key in list(counts):
        counts[key] = max(int(counts[key]), int(rejection_labeling.get(key, 0) or 0))
    total = sum(counts.values())
    return {
        **counts,
        "market_closed_rejection_dominant": counts["market_closed_rejection_count"] > 0 and counts["market_closed_rejection_count"] >= max(1, total - counts["market_closed_rejection_count"]),
        "market_data_rejection_total": total,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
