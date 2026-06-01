"""Drawdown recovery decision policy."""

from __future__ import annotations

from typing import Any, Mapping


def build_drawdown_recovery_plan(
    *,
    safety_blocked: bool,
    closed_audit: Mapping[str, Any],
    open_audit: Mapping[str, Any],
    ledger_audit: Mapping[str, Any],
    paper_state_audit: Mapping[str, Any],
    quarantined_trade_count: int,
) -> dict[str, Any]:
    if safety_blocked:
        return _plan("MICRO_V2_DRAWDOWN_STATE_SAFETY_BLOCKED", "SAFETY_FLAGS_TRUE", False)
    if closed_audit.get("closed_trade_integrity_status") != "CLOSED_TRADE_INTEGRITY_OK":
        return _plan("MICRO_V2_DRAWDOWN_HALT_CLOSED_TRADE_INTEGRITY_ISSUE", "Closed paper trade integrity issue requires manual review.", False)
    if open_audit.get("open_trade_integrity_status") != "OPEN_TRADE_INTEGRITY_OK":
        return _plan("MICRO_V2_DRAWDOWN_HALT_OPEN_TRADE_INTEGRITY_ISSUE", "Open paper trade integrity issue requires manual review.", False)
    if paper_state_audit.get("drawdown_halt_root_cause") == "LEGITIMATE_CLOSED_PAPER_LOSS_DRAWDOWN":
        return _plan("MICRO_V2_DRAWDOWN_HALT_LEGITIMATE", "Daily drawdown halt is supported by recorded closed paper losses.", False)
    if quarantined_trade_count and paper_state_audit.get("drawdown_halt_root_cause") == "QUARANTINE_CONTAMINATION":
        return _plan("MICRO_V2_DRAWDOWN_HALT_QUARANTINE_CONTAMINATION", "Prepare deterministic V2-only quarantine exclusion repair.", True)
    if ledger_audit.get("ledger_scope_mismatch"):
        return _plan("MICRO_V2_DRAWDOWN_HALT_LEDGER_SCOPE_MISMATCH", "Prepare V2-scoped daily risk ledger repair.", True)
    if paper_state_audit.get("paper_daily_drawdown_halt_detected"):
        return _plan("MICRO_V2_DRAWDOWN_STATE_REQUIRES_MANUAL_REVIEW", "Drawdown halt requires manual review.", False)
    return _plan("MICRO_V2_DRAWDOWN_STATE_NO_REPAIR_NEEDED", "No active drawdown repair required.", False)


def _plan(status: str, reason: str, repair_allowed: bool) -> dict[str, Any]:
    return {
        "micro_v2_daily_drawdown_state_recovery_status": status,
        "drawdown_halt_root_cause": reason,
        "repair_recommended": repair_allowed,
        "repair_allowed": repair_allowed,
        "repair_applied": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
