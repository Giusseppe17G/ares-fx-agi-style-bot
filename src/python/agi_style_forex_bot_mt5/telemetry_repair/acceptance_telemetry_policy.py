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
    if status == "TELEMETRY_HISTORICAL_ISSUES_ONLY" and not clear:
        return True, "NEEDS_TELEMETRY_REVIEW", "Historical invalid timestamps must be quarantined or reviewed before acceptance."
    return False, "", ""
