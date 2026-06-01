"""Consolidated reset/relaunch gate for Micro V2 pre-relaunch pack."""

from __future__ import annotations

from typing import Any, Mapping


def evaluate_reset_relaunch_gate(reset_summary: Mapping[str, Any]) -> dict[str, Any]:
    daily_halt_active = bool(reset_summary.get("daily_halt_active", False))
    daily_reset_occurred = bool(reset_summary.get("daily_reset_occurred", False))
    relaunch_allowed = bool(reset_summary.get("relaunch_allowed", False))
    scope_status = str(reset_summary.get("daily_risk_scope_status") or "")
    if relaunch_allowed:
        status = "MICRO_V2_PRE_RELAUNCH_SAFETY_PACK_READY_FOR_RELAUNCH"
    elif daily_halt_active:
        status = "MICRO_V2_RELAUNCH_GATE_DAILY_HALT_ACTIVE"
    elif scope_status != "DAILY_RISK_SCOPE_OK_FOR_V2":
        status = "MICRO_V2_RELAUNCH_GATE_SCOPE_INVALID"
    elif not bool(reset_summary.get("paper_state_clean_for_relaunch", False)):
        status = "MICRO_V2_RELAUNCH_GATE_PAPER_STATE_BLOCK"
    else:
        status = "MICRO_V2_PRE_RELAUNCH_REQUIRES_MANUAL_REVIEW"
    return {
        "reset_relaunch_gate_status": status,
        "daily_halt_active": daily_halt_active,
        "daily_reset_occurred": daily_reset_occurred,
        "daily_risk_scope_status": scope_status,
        "open_trade_count": int(reset_summary.get("open_trade_count", 0) or 0),
        "invalid_open_trade_count": int(reset_summary.get("invalid_open_trade_count", 0) or 0),
        "quarantined_trade_count": int(reset_summary.get("quarantined_trade_count", 0) or 0),
        "paper_state_clean_for_relaunch": bool(reset_summary.get("paper_state_clean_for_relaunch", False)),
        "relaunch_allowed": relaunch_allowed,
        "recommended_next_action": "RELAUNCH_V2_PAPER_DRY_RUN_MANUALLY" if relaunch_allowed else "KEEP_V2_STOPPED_AND_RERUN_RESET_READINESS_LATER",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
