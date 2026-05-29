"""Categorize forward blockers into profile throttle buckets."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .blocker_funnel import _is_blocking_event
from .rejection_funnel import _reason


BUCKET_PATTERNS = {
    "session_block_count": ("SESSION",),
    "score_threshold_block_count": ("SCORE", "THRESHOLD", "ENSEMBLE"),
    "spread_block_count": ("SPREAD", "COST"),
    "stale_signal_count": ("STALE", "FUTURE", "TIMESTAMP"),
    "regime_block_count": ("REGIME",),
    "liquidity_block_count": ("LIQUIDITY",),
    "cooldown_block_count": ("COOLDOWN",),
    "paper_risk_block_count": ("PAPER_RISK", "DRAWDOWN", "MAX_OPEN", "DAILY_TRADE_LIMIT"),
    "data_quality_block_count": ("DATA", "FEATURE", "SCHEMA", "MT5", "TICK", "RATES", "MARKET_DATA"),
}


def audit_profile_throttle(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    buckets = {key: 0 for key in BUCKET_PATTERNS}
    reasons: Counter[str] = Counter()
    for event in events:
        if not _is_blocking_event(event):
            continue
        reason = _reason(event)
        upper = reason.upper()
        if reason:
            reasons[reason] += 1
        for bucket, patterns in BUCKET_PATTERNS.items():
            if any(pattern in upper for pattern in patterns):
                buckets[bucket] += 1
    profile_throttle_reasons = [
        {"blocking_reason": reason, "count": count}
        for reason, count in reasons.most_common(10)
        if _is_profile_throttle_reason(reason)
    ]
    return {
        **buckets,
        "profile_throttle_reasons": profile_throttle_reasons,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _is_profile_throttle_reason(reason: str) -> bool:
    upper = reason.upper()
    return any(any(pattern in upper for pattern in patterns) for patterns in BUCKET_PATTERNS.values())
