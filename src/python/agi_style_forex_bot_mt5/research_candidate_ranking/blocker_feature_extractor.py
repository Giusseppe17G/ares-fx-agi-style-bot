"""Blocker feature extraction for offline candidate ranking."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def blocker_features(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    reasons = [str(event.get("reason") or "UNKNOWN") for event in events if event.get("is_rejection")]
    counter = Counter(_canonical(reason) for reason in reasons)
    total = sum(counter.values())
    return {
        "signals_rejected": total,
        "top_blocking_reasons": ";".join(f"{reason}:{count}" for reason, count in counter.most_common(5)),
        "session_block_count": _count_contains(counter, "SESSION"),
        "component_score_low_count": _count_contains(counter, "SCORE") + _count_contains(counter, "ENSEMBLE") + _count_contains(counter, "COMPONENT"),
        "spread_rejection_count": _count_contains(counter, "SPREAD") + _count_contains(counter, "COST"),
        "stale_signal_count": _count_contains(counter, "STALE") + _count_contains(counter, "FUTURE"),
        "liquidity_sweep_missing_count": _count_contains(counter, "LIQUIDITY"),
        "execution_attempted": False,
    }


def _canonical(reason: str) -> str:
    text = reason.upper().strip()
    if "SPREAD" in text:
        return "SPREAD_BLOCK"
    if "COST" in text:
        return "COST_BLOCK"
    if "STALE" in text or "FUTURE" in text:
        return "STALE_SIGNAL"
    if "ENSEMBLE" in text or "SCORE" in text:
        return "ENSEMBLE_SCORE_LOW"
    if "SESSION" in text:
        return "SESSION_BLOCK"
    if "REGIME" in text:
        return "REGIME_BLOCK"
    if "SYMBOL" in text:
        return "SYMBOL_REJECTED"
    return text or "UNKNOWN"


def _count_contains(counter: Counter[str], token: str) -> int:
    return sum(count for reason, count in counter.items() if token in reason)
