"""Manual review decision for paper drawdown halt clearance."""

from __future__ import annotations

from typing import Any, Mapping


def decide_manual_review(context: Mapping[str, Any]) -> dict[str, Any]:
    """Classify whether the halt evidence is ready for manual clearance."""

    if int(context.get("paper_trades_open", 0) or 0) > 0 or not bool(context.get("paper_state_clean", False)):
        return _decision("PAPER_RISK_REVIEW_BLOCKED_OPEN_TRADES", "Close or inspect open paper trades before clearance.")
    if not bool(context.get("execution_evidence_clear", False)):
        return _decision("PAPER_RISK_REVIEW_BLOCKED_EXECUTION_EVIDENCE", "Execution evidence is not clear.")
    if not bool(context.get("telemetry_clear", False)):
        return _decision("PAPER_RISK_REVIEW_BLOCKED_TELEMETRY", "Telemetry is not clean or quarantined.")
    if not bool(context.get("micro_profile_exists", False)):
        return _decision("PAPER_RISK_REVIEW_BLOCKED_NO_MICRO_PROFILE", "BALANCED_STABLE_MICRO profile config is missing.")
    if not bool(context.get("stable_gate_exists", False)) or not bool(context.get("stable_gate_ready", False)):
        return _decision("PAPER_RISK_REVIEW_REQUIRED", "Stable gate is missing or not PAPER_SHADOW_READY.")
    if context.get("latest_halt"):
        return _decision("PAPER_RISK_REVIEW_READY_FOR_CLEARANCE", "Paper halt can be cleared for BALANCED_STABLE_MICRO paper/shadow only.")
    return _decision("PAPER_RISK_REVIEW_REQUIRED", "No PAPER_DAILY_DRAWDOWN_HALT evidence found.")


def _decision(classification: str, reason: str) -> dict[str, Any]:
    return {
        "classification": classification,
        "paper_risk_review_status": classification,
        "reason": reason,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
