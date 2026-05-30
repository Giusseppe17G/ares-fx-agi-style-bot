"""Safety guard checks before granting BALANCED_STABLE_MICRO_V2 clearance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.micro_v2_dry_run_readiness.v2_profile_guard import audit_v2_profile

from .clearance_ledger_adapter import load_json


def audit_v2_clearance_prerequisites(
    *,
    v2_profile_config: str | Path,
    micro_v2_review_dir: str | Path,
    runtime_profile_check_dir: str | Path,
) -> dict[str, Any]:
    profile_guard = audit_v2_profile(v2_profile_config)
    phase48 = load_json(Path(micro_v2_review_dir) / "micro_v2_proposed_review_summary.json")
    phase50 = load_json(Path(runtime_profile_check_dir) / "micro_v2_runtime_profile_check_summary.json")
    failures: list[dict[str, Any]] = []
    if profile_guard.get("profile_guard_status") != "PASS":
        failures.append(_failure("V2_PROFILE", "BALANCED_STABLE_MICRO_V2 profile guard failed."))
    if phase48.get("micro_v2_proposed_review_status") != "MICRO_V2_PROPOSED_APPROVED_FOR_PAPER_DRY_RUN" or phase48.get("micro_v2_profile_created") is not True:
        failures.append(_failure("PHASE48", "FASE 48 proposed review is missing or not approved."))
    if (
        phase50.get("micro_v2_runtime_profile_check_status") != "MICRO_V2_SIGNAL_PROFILE_REGISTERED"
        or phase50.get("runtime_guard_status") != "MICRO_V2_RUNTIME_GUARDS_PASSED"
        or phase50.get("launch_command_invalid_choice_resolved") is not True
    ):
        failures.append(_failure("PHASE50", "FASE 50 runtime registration is missing or not approved."))
    status = _status_from_failures(failures)
    return {
        "clearance_guard_status": "PASS" if not failures else "FAIL",
        "micro_v2_clearance_status": status,
        "failures": failures,
        "profile_guard": profile_guard,
        "phase48_summary_path": str(Path(micro_v2_review_dir) / "micro_v2_proposed_review_summary.json"),
        "phase48_status": phase48.get("micro_v2_proposed_review_status", ""),
        "phase48_profile_created": bool(phase48.get("micro_v2_profile_created", False)),
        "phase50_summary_path": str(Path(runtime_profile_check_dir) / "micro_v2_runtime_profile_check_summary.json"),
        "phase50_status": phase50.get("micro_v2_runtime_profile_check_status", ""),
        "phase50_runtime_guard_status": phase50.get("runtime_guard_status", ""),
        "phase50_invalid_choice_resolved": bool(phase50.get("launch_command_invalid_choice_resolved", False)),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _status_from_failures(failures: list[dict[str, Any]]) -> str:
    if not failures:
        return "MICRO_V2_PAPER_RISK_CLEARANCE_GRANTED"
    keys = {str(item.get("key", "")) for item in failures}
    if "V2_PROFILE" in keys:
        return "MICRO_V2_CLEARANCE_REJECTED_PROFILE_INVALID"
    if "PHASE48" in keys:
        return "MICRO_V2_CLEARANCE_REJECTED_PHASE48_MISSING"
    if "PHASE50" in keys:
        return "MICRO_V2_CLEARANCE_REJECTED_PHASE50_MISSING"
    return "MICRO_V2_CLEARANCE_REQUIRES_MANUAL_REVIEW"


def _failure(key: str, reason: str) -> dict[str, Any]:
    return {"key": key, "reason": reason, "execution_attempted": False, "order_send_called": False, "order_check_called": False}
