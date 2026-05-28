"""Telemetry acceptance policy for forward evidence."""

from __future__ import annotations

from typing import Any, Mapping


def telemetry_gate_decision(telemetry_summary: Mapping[str, Any] | None) -> tuple[bool, str, str]:
    """Return (blocked, decision, reason) for telemetry state."""

    if not telemetry_summary:
        return False, "", ""
    status = str(telemetry_summary.get("telemetry_status", ""))
    clear = bool(telemetry_summary.get("telemetry_acceptance_clear", False))
    if status == "TELEMETRY_ACTIVE_BLOCKING":
        return True, "NEEDS_TELEMETRY_FIX", "Forward evidence contains active invalid or redacted timestamps."
    if status == "TELEMETRY_UNKNOWN_REVIEW_REQUIRED":
        return True, "NEEDS_TELEMETRY_REVIEW", "Forward evidence contains timestamp issues requiring manual review."
    if status in {"TELEMETRY_CLEAN", "TELEMETRY_HISTORICAL_QUARANTINED"}:
        return False, "", ""
    historical_invalid = int(telemetry_summary.get("historical_invalid_count", 0) or 0)
    quarantined = int(telemetry_summary.get("quarantined_count", telemetry_summary.get("historical_quarantined_count", 0)) or 0)
    reviewed = int(telemetry_summary.get("reviewed_count", telemetry_summary.get("historical_reviewed_count", 0)) or 0)
    unreviewed = int(telemetry_summary.get("historical_unreviewed_count", telemetry_summary.get("unreviewed_count", telemetry_summary.get("unquarantined_historical_count", 0))) or 0)
    unknown = int(telemetry_summary.get("unknown_requires_review", 0) or 0)
    active = int(telemetry_summary.get("active_blocking_count", 0) or 0)
    if active > 0:
        return True, "NEEDS_TELEMETRY_FIX", "Forward evidence contains active invalid or redacted timestamps."
    if unknown > 0:
        return True, "NEEDS_TELEMETRY_REVIEW", "Forward evidence contains timestamp issues requiring manual review."
    if active == 0 and unknown == 0 and historical_invalid > 0 and unreviewed == 0 and quarantined + reviewed >= historical_invalid:
        return False, "", ""
    if unreviewed > 0:
        return True, "NEEDS_TELEMETRY_REVIEW", "Historical invalid timestamps must be quarantined or reviewed before acceptance."
    if status == "TELEMETRY_HISTORICAL_ISSUES_ONLY" and not clear:
        return True, "NEEDS_TELEMETRY_REVIEW", "Historical invalid timestamps must be quarantined or reviewed before acceptance."
    return False, "", ""
