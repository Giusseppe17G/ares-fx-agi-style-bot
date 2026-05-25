"""Patch helpers for forward acceptance execution guard decisions."""

from __future__ import annotations

from typing import Any, Mapping


BLOCKING_STATUSES = {"EXECUTION_EVIDENCE_BLOCKED_REAL_ATTEMPT", "EXECUTION_EVIDENCE_UNKNOWN_REVIEW_REQUIRED"}
CLEAR_STATUSES = {"EXECUTION_EVIDENCE_CLEAR", "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"}


def execution_guard_decision(summary: Mapping[str, Any]) -> tuple[bool, str]:
    """Return (blocked, reason) from an execution evidence summary."""

    status = str(summary.get("execution_evidence_status") or "")
    if status == "EXECUTION_EVIDENCE_BLOCKED_REAL_ATTEMPT":
        return True, "Execution evidence contains a true order/execution attempt field."
    if status == "EXECUTION_EVIDENCE_UNKNOWN_REVIEW_REQUIRED":
        return True, "Execution evidence contains unknown/ambiguous order evidence requiring review."
    if status in CLEAR_STATUSES:
        return False, ""
    return False, ""
