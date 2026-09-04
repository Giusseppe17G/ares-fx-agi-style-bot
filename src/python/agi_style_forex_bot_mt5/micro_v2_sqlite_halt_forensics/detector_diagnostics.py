"""Diagnostics explaining current halt detector misses."""

from __future__ import annotations

from typing import Any, Mapping


def diagnose_current_detector(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    matched = [event for event in events if event.get("current_is_halt_event_match")]
    missed = [event for event in events if not event.get("current_is_halt_event_match")]
    in_scope = [event for event in missed if event.get("detector_miss_reason") != "SOURCE_NOT_IN_CURRENT_EVENTS_DATASET"]
    token_events = [event for event in events if event.get("halt_evidence_class") == "HALT_TOKEN"]
    state_events = [event for event in events if event.get("halt_evidence_class") == "HALT_STATE_FIELD"]
    reasons: dict[str, int] = {}
    for event in missed:
        reason = str(event.get("detector_miss_reason", "UNKNOWN"))
        reasons[reason] = reasons.get(reason, 0) + 1
    likely_causes = []
    if reasons.get("ALERT_CODE_ONLY_IN_SQLITE_COLUMN_NOT_PAYLOAD"):
        likely_causes.append("current _is_halt_event checks payload.alert_code but SQLite alerts store alert_code as a table column")
    if reasons.get("SOURCE_NOT_IN_CURRENT_EVENTS_DATASET"):
        likely_causes.append("halt evidence exists outside the events dataset scanned by current _is_halt_event")
    if reasons.get("HALT_STATE_STORED_IN_OPERATIONAL_STATE_NOT_EVENTS_DATASET"):
        likely_causes.append("current daily reset detector scans events only and misses operational_state halt_reason/shadow_paused")
    if reasons.get("EVENT_RENAMED_TO_PAPER_SHADOW_HALTED_WITHOUT_DRAWDOWN_TOKEN"):
        likely_causes.append("some halt events are emitted as PAPER_SHADOW_HALTED and need payload halt_reason fallback")
    if reasons.get("HALT_TOKEN_OUTSIDE_CURRENT_DETECTOR_FIELDS"):
        likely_causes.append("halt token exists outside event_type/message/payload.halt_reason/payload.alert_code")
    return {
        "current_detector_name": "micro_v2_daily_reset_readiness.daily_halt_status_audit._is_halt_event",
        "current_detector_logic": "case-sensitive search for PAPER_DAILY_DRAWDOWN/PAPER_DAILY_DRAWDOWN_HALT in event_type, message, payload.halt_reason, payload.alert_code",
        "events_seen_by_forensics": len(events),
        "current_detector_match_count": len(matched),
        "current_detector_miss_count": len(missed),
        "halt_token_event_count": len(token_events),
        "halt_state_field_event_count": len(state_events),
        "in_scope_detector_miss_count": len(in_scope),
        "out_of_scope_detector_miss_count": len(missed) - len(in_scope),
        "miss_reasons": dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
        "likely_root_causes": likely_causes,
        "recommended_next_action": "Review detector field coverage before any repair; do not auto-repair in FASE 78.",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
