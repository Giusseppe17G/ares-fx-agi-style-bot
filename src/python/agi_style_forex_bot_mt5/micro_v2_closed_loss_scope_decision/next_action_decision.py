"""Decision policy for closed loss scope audit."""

from __future__ import annotations

from typing import Any, Mapping


def decide_next_action(
    *,
    safety_blocked: bool,
    attribution: Mapping[str, Any],
    quarantine: Mapping[str, Any],
    legitimacy: Mapping[str, Any],
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    if safety_blocked:
        return _decision("MICRO_V2_SAFETY_BLOCKED", "STOP_AND_REVIEW_SAFETY_FLAGS")
    if quarantine.get("quarantined_contamination_detected"):
        return _decision("MICRO_V2_CLOSED_LOSSES_QUARANTINE_CONTAMINATION", "PREPARE_QUARANTINE_CONTAMINATION_REPAIR")
    if attribution.get("pnl_integrity_status") != "PNL_INTEGRITY_OK":
        return _decision("MICRO_V2_CLOSED_LOSSES_PNL_INTEGRITY_ISSUE", "PREPARE_PNL_FORENSIC_REPAIR")
    if legitimacy.get("closed_loss_legitimate"):
        scope_status = str(scope.get("daily_risk_scope_status") or "")
        if scope_status == "DAILY_RISK_SCOPE_MISMATCH_REPAIR_NEEDED":
            return _decision("MICRO_V2_CLOSED_LOSSES_LEGITIMATE_KEEP_DAILY_HALT", "KEEP_DAILY_HALT_AND_PREPARE_LEDGER_SCOPE_REPAIR_PHASE")
        if scope_status == "DAILY_RISK_SCOPE_VALID":
            return _decision("MICRO_V2_DAILY_RISK_SCOPE_VALID_WAIT_FOR_RESET", "WAIT_FOR_DAILY_RESET_BEFORE_RESTART")
        if scope_status == "DAILY_RISK_SCOPE_MISMATCH_METADATA_ONLY":
            return _decision("MICRO_V2_DAILY_RISK_SCOPE_MISMATCH_METADATA_ONLY", "KEEP_HALT_REVIEW_LEDGER_METADATA")
        return _decision("MICRO_V2_CLOSED_LOSSES_LEGITIMATE_KEEP_DAILY_HALT", "KEEP_DAILY_HALT_REVIEW_LEDGER_SCOPE")
    return _decision("MICRO_V2_CLOSED_LOSSES_REQUIRES_MANUAL_REVIEW", "MANUAL_REVIEW_REQUIRED")


def _decision(status: str, next_action: str) -> dict[str, Any]:
    return {
        "micro_v2_closed_loss_scope_decision_status": status,
        "next_allowed_action": next_action,
        "recommended_next_action": next_action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
