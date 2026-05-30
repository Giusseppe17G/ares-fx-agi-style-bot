"""Readiness decision for V2 dry-run launch planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def audit_readiness(
    *,
    profile_guard: Mapping[str, Any],
    path_isolation: Mapping[str, Any],
    stable_gate: str | Path,
    paper_risk_clearance: str | Path | None,
    daily_risk_ledger: str | Path | None,
) -> dict[str, Any]:
    missing = []
    if not Path(stable_gate).exists():
        missing.append("stable_gate")
    if not paper_risk_clearance or not Path(paper_risk_clearance).exists():
        missing.append("paper_risk_clearance")
    if not daily_risk_ledger or not Path(daily_risk_ledger).exists():
        missing.append("daily_risk_ledger")
    if missing:
        status = "MICRO_V2_LEDGER_REQUIREMENTS_MISSING"
    elif profile_guard.get("profile_guard_status") != "PASS":
        failures = profile_guard.get("failures", [])
        text = str(failures).upper()
        status = "MICRO_V2_NOT_APPROVED_FOR_DRY_RUN" if "APPROVED_FOR_PAPER_DRY_RUN_ONLY" in text else "MICRO_V2_PROFILE_INVALID"
    elif path_isolation.get("path_isolation_status") != "PASS":
        status = "MICRO_V2_PATH_ISOLATION_FAILED"
    else:
        status = "MICRO_V2_DRY_RUN_READY"
    return {
        "micro_v2_dry_run_readiness_status": status,
        "missing_requirements": missing,
        "recommended_next_action": _recommended_action(status),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _recommended_action(status: str) -> str:
    return {
        "MICRO_V2_DRY_RUN_READY": "MANUALLY_LAUNCH_V2_DRY_RUN_ONLY_AFTER_EXPLICIT_APPROVAL",
        "MICRO_V2_PROFILE_INVALID": "FIX_V2_PROFILE_GUARDS_OFFLINE",
        "MICRO_V2_GUARDS_FAILED": "FIX_V2_GUARDS_OFFLINE",
        "MICRO_V2_PATH_ISOLATION_FAILED": "USE_SEPARATE_V2_SQLITE_AND_LOG_DIR",
        "MICRO_V2_LEDGER_REQUIREMENTS_MISSING": "RESTORE_REQUIRED_STABLE_GATE_AND_LEDGERS",
        "MICRO_V2_NOT_APPROVED_FOR_DRY_RUN": "RUN_PROPOSED_REVIEW_OR_FIX_APPROVAL_MARKERS",
    }.get(status, "MANUAL_REVIEW_REQUIRED")
