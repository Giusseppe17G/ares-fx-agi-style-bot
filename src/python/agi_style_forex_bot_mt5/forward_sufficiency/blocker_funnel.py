"""Blocking reason funnel aggregation."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .rejection_funnel import REJECTION_EVENTS, _reason


def build_blocker_funnel(events: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counter: Counter[str] = Counter()
    for event in events:
        if not _is_blocking_event(event):
            continue
        reason = _reason(event)
        if reason and reason != "UNKNOWN":
            counter[reason] += 1
    rows = [
        {"blocking_reason": reason, "count": count, "execution_attempted": False, "order_send_called": False, "order_check_called": False}
        for reason, count in counter.most_common()
    ]
    return rows, {
        "top_blocking_reasons": rows[:10],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _is_blocking_event(event: Mapping[str, Any]) -> bool:
    event_type = str(event.get("event_type", "")).upper()
    if event_type in REJECTION_EVENTS:
        return True
    return any(token in event_type for token in ("BLOCK", "REJECT", "HALT", "ERROR", "ALERT"))
