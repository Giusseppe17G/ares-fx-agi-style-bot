"""Rejection pressure calculations for micro frequency calibration."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from agi_style_forex_bot_mt5.forward_sufficiency.rejection_funnel import REJECTION_EVENTS

from .frequency_dataset import event_reason, event_strategy


SIGNAL_EVENTS = {
    "SIGNAL_DETECTED",
    "SIGNAL_ACCEPTED",
    "SIGNAL_REJECTED",
    "RISK_REJECTED",
    "SYMBOL_REJECTED",
    "STALE_TICK_REJECTION",
    "MARKET_CLOSED_REJECTION",
    "FUTURE_SIGNAL_REJECTION",
    "INVALID_MARKET_SNAPSHOT_REJECTION",
    "STRATEGY_BLOCKED_BY_CONTEXT",
    "FORWARD_CANDIDATE_EVALUATED",
    "FORWARD_CANDIDATE_BLOCKED",
    "FORWARD_NEAR_MISS",
    "PAPER_TRADE_OPENED",
}


def audit_rejection_pressure(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    reason_counts: Counter[str] = Counter()
    strategy_counts: Counter[str] = Counter()
    signals = 0
    rejected = 0
    accepted = 0
    for event in events:
        event_type = str(event.get("event_type", ""))
        if event_type in SIGNAL_EVENTS or event_type in REJECTION_EVENTS:
            signals += 1
        if event_type in REJECTION_EVENTS:
            rejected += 1
            reason_counts[event_reason(event)] += 1
            strategy_counts[event_strategy(event)] += 1
        elif event_type in {"SIGNAL_ACCEPTED", "PAPER_TRADE_OPENED"}:
            accepted += 1
    return {
        "signals_detected": signals,
        "signals_rejected": rejected,
        "signals_accepted": accepted,
        "rejection_rate": round(rejected / signals, 4) if signals else 0.0,
        "top_rejection_reasons": [{"reason": reason, "count": count} for reason, count in reason_counts.most_common(10)],
        "top_rejected_strategies": [{"strategy_name": strategy, "count": count} for strategy, count in strategy_counts.most_common(10)],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
