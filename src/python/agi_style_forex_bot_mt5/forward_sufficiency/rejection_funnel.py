"""Rejected signal funnel aggregation."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


REJECTION_EVENTS = {
    "SIGNAL_REJECTED",
    "RISK_REJECTED",
    "SYMBOL_REJECTED",
    "STALE_TICK_REJECTION",
    "MARKET_CLOSED_REJECTION",
    "FUTURE_SIGNAL_REJECTION",
    "INVALID_MARKET_SNAPSHOT_REJECTION",
    "STRATEGY_BLOCKED_BY_CONTEXT",
    "FORWARD_CANDIDATE_BLOCKED",
    "FORWARD_NO_SIGNAL_DIAGNOSTIC",
}


def build_rejection_funnel(events: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counter: Counter[str] = Counter()
    for event in events:
        if str(event.get("event_type", "")) not in REJECTION_EVENTS:
            continue
        counter[_reason(event)] += 1
    rows = [
        {"rejection_reason": reason, "count": count, "execution_attempted": False, "order_send_called": False, "order_check_called": False}
        for reason, count in counter.most_common()
    ]
    return rows, {
        "signals_rejected": sum(counter.values()),
        "top_rejection_reasons": rows[:10],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _reason(event: Mapping[str, Any]) -> str:
    payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
    reasons = payload.get("blocking_reasons")
    if isinstance(reasons, list) and reasons:
        return str(reasons[0])
    return str(
        payload.get("reject_reason")
        or payload.get("reject_code")
        or payload.get("blocking_reason")
        or payload.get("reason")
        or event.get("message")
        or event.get("event_type")
        or "UNKNOWN"
    )
