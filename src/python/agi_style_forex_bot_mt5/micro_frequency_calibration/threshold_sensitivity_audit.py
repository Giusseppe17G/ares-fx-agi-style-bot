"""Offline score/threshold sensitivity diagnostics."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from agi_style_forex_bot_mt5.forward_sufficiency.blocker_funnel import _is_blocking_event

from .frequency_dataset import event_reason


def audit_threshold_sensitivity(events: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counter: Counter[str] = Counter()
    score_values: list[float] = []
    for event in events:
        if not _is_blocking_event(event):
            continue
        reason = event_reason(event)
        upper = reason.upper()
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        if any(token in upper for token in ("SCORE", "THRESHOLD", "ENSEMBLE")):
            counter[reason] += 1
            score = payload.get("ensemble_score") or payload.get("signal_score") or payload.get("setup_score")
            try:
                score_values.append(float(score))
            except Exception:
                pass
    rows = [
        {
            "threshold_block_reason": reason,
            "count": count,
            "candidate_adjustment": "MANUAL_PROFILE_REVIEW_REQUIRED",
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
        for reason, count in counter.most_common()
    ]
    avg_score = sum(score_values) / len(score_values) if score_values else 0.0
    return rows, {
        "score_threshold_block_count": sum(counter.values()),
        "average_blocked_score": round(avg_score, 4),
        "manual_threshold_review_required": bool(counter),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
