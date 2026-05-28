"""Operational acceptance gate for BALANCED_STABLE forward evidence."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.execution_evidence.acceptance_gate_patch import execution_guard_decision
from agi_style_forex_bot_mt5.telemetry_repair.acceptance_telemetry_policy import telemetry_gate_decision

from .acceptance_drawdown_policy import evaluate_acceptance_drawdown_policy


def decide_operational_acceptance(
    *,
    evidence: Mapping[str, Any],
    metrics: Mapping[str, Any],
    drift: Mapping[str, Any],
    paper_audit: Mapping[str, Any],
    execution_evidence: Mapping[str, Any] | None = None,
    telemetry_summary: Mapping[str, Any] | None = None,
    paper_risk: Mapping[str, Any] | None = None,
    legacy_drawdown: Mapping[str, Any] | None = None,
    paper_state_recovery: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a conservative operational decision for paper/shadow continuation."""

    if execution_evidence:
        blocked, reason = execution_guard_decision(execution_evidence)
        if blocked:
            return _decision("PAUSE_FORWARD_SHADOW", reason)
    else:
        # Legacy fallback: only true booleans block. Safe false fields and text mentions do not.
        if evidence.get("execution_attempted") is True or evidence.get("order_send_called") is True or evidence.get("order_check_called") is True:
            return _decision("PAUSE_FORWARD_SHADOW", "Execution path was attempted or broker order function appeared in evidence.")
    telemetry_blocked, telemetry_decision, telemetry_reason = telemetry_gate_decision(telemetry_summary)
    if telemetry_blocked:
        return _decision(telemetry_decision, telemetry_reason)
    drawdown_policy = evaluate_acceptance_drawdown_policy(metrics=metrics, evidence=evidence, telemetry_summary=telemetry_summary, paper_risk=paper_risk, legacy_drawdown=legacy_drawdown)
    if drawdown_policy.get("acceptance_drawdown_blocking"):
        return _decision("PAUSE_FORWARD_SHADOW", str(drawdown_policy.get("acceptance_blocking_reason") or "Paper daily drawdown halt is active."), drawdown_policy)
    recovery = dict(paper_state_recovery or {})
    policy = {**drawdown_policy, **_recovery_policy_fields(recovery)}
    if recovery.get("recovery_required") and not recovery.get("can_safely_continue_with_open_trade"):
        return _decision(
            "PAUSE_FORWARD_SHADOW",
            str(recovery.get("recovery_recommended_action") or "Paper state recovery is required before acceptance."),
            policy,
        )
    if telemetry_summary is None and int(evidence.get("invalid_timestamp_count", 0) or 0) > 0:
        return _decision("NEEDS_TELEMETRY_FIX", "Forward evidence contains invalid or redacted timestamps.", policy)
    if not bool(evidence.get("stable_gate_confirmed")):
        return _decision("PAUSE_FORWARD_SHADOW", "Stable gate is missing.", policy)
    if int(evidence.get("heartbeat_count", 0) or 0) == 0:
        return _decision("PAUSE_FORWARD_SHADOW", "Missing heartbeat evidence.", policy)
    if str(paper_audit.get("status")) != "OK":
        return _decision("PAUSE_FORWARD_SHADOW", "Paper trade audit failed.", policy)
    if str(drift.get("classification")) == "CRITICAL_DRIFT":
        return _decision("PAUSE_FORWARD_SHADOW", "Critical forward drift detected.", policy)
    if float(evidence.get("hours_observed", 0.0) or 0.0) < 24 or int(metrics.get("closed_trades", 0) or 0) < 10:
        return _decision("NEEDS_MORE_FORWARD_DATA", "Forward observation has no critical issues but needs at least 24 hours and 10 closed paper trades.", policy)
    if str(drift.get("classification")) == "WATCHLIST_DRIFT":
        return _decision("NEEDS_STABILITY_REPAIR", "Watchlist drift requires stability review before extended continuation.", policy)
    return _decision("CONTINUE_FORWARD_SHADOW", "Forward evidence is healthy enough to continue paper/shadow observation.", policy)


def _decision(decision: str, reason: str, drawdown_policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    drawdown_policy = dict(drawdown_policy or {})
    return {
        "mode": "forward-acceptance",
        "classification": decision,
        "decision": decision,
        "reason": reason,
        "paper_daily_risk_status": drawdown_policy.get("paper_daily_risk_status", ""),
        "legacy_drawdown_status": drawdown_policy.get("legacy_drawdown_status", ""),
        "legacy_drawdown_quarantined": bool(drawdown_policy.get("legacy_drawdown_quarantined", False)),
        "active_scaled_drawdown_count": int(drawdown_policy.get("active_scaled_drawdown_count", 0) or 0),
        "drawdown_basis": drawdown_policy.get("drawdown_basis", ""),
        "daily_risk_ledger_status": drawdown_policy.get("daily_risk_ledger_status", ""),
        "paper_risk_status": drawdown_policy.get("paper_risk_status", ""),
        "paper_state_recovery_status": drawdown_policy.get("paper_state_recovery_status", ""),
        "config_error_root_cause": drawdown_policy.get("config_error_root_cause", ""),
        "config_error_recommended_fix": drawdown_policy.get("config_error_recommended_fix", ""),
        "config_error_resolved": bool(drawdown_policy.get("config_error_resolved", False)),
        "invalid_open_paper_trade_count": int(drawdown_policy.get("invalid_open_paper_trade_count", 0) or 0),
        "invalid_open_paper_trade_resolved": bool(drawdown_policy.get("invalid_open_paper_trade_resolved", False)),
        "can_rerun_forward_shadow_after_fix": bool(drawdown_policy.get("can_rerun_forward_shadow_after_fix", False)),
        "open_paper_trade_audit_status": drawdown_policy.get("open_paper_trade_audit_status", ""),
        "paper_state_clean_for_observation": bool(drawdown_policy.get("paper_state_clean_for_observation", True)),
        "recovery_required": bool(drawdown_policy.get("recovery_required", False)),
        "recovery_recommended_action": drawdown_policy.get("recovery_recommended_action", ""),
        "telemetry_acceptance_clear": bool(drawdown_policy.get("telemetry_acceptance_clear", False)),
        "acceptance_drawdown_blocking": bool(drawdown_policy.get("acceptance_drawdown_blocking", False)),
        "acceptance_blocking_reason": str(drawdown_policy.get("acceptance_blocking_reason", "")),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _recovery_policy_fields(recovery: Mapping[str, Any]) -> dict[str, Any]:
    status = "OK"
    if int(recovery.get("orphan_open_trade_count", 0) or 0) > 0:
        status = "ORPHAN_OPEN_PAPER_TRADE"
    elif int(recovery.get("invalid_risk_open_trade_count", 0) or 0) > 0:
        status = "INVALID_RISK_OPEN_PAPER_TRADE"
    elif int(recovery.get("stale_open_trade_count", 0) or 0) > 0:
        status = "STALE_OPEN_PAPER_TRADE"
    elif int(recovery.get("valid_open_trade_count", 0) or 0) > 0:
        status = "VALID_OPEN_PAPER_TRADE"
    return {
        "paper_state_recovery_status": recovery.get("paper_state_recovery_status", ""),
        "config_error_root_cause": recovery.get("config_error_root_cause", ""),
        "config_error_recommended_fix": recovery.get("recommended_config_fix", ""),
        "config_error_resolved": bool(recovery.get("config_error_resolved", False)),
        "invalid_open_paper_trade_count": int(recovery.get("invalid_risk_open_trade_count", 0) or 0),
        "invalid_open_paper_trade_resolved": int(recovery.get("invalid_risk_open_trade_count", 0) or 0) == 0,
        "can_rerun_forward_shadow_after_fix": bool(recovery.get("can_rerun_forward_shadow_after_fix", False)),
        "open_paper_trade_audit_status": status,
        "paper_state_clean_for_observation": bool(recovery.get("paper_state_clean_for_observation", False)),
        "recovery_required": bool(recovery.get("recovery_required", False)),
        "recovery_recommended_action": recovery.get("recovery_recommended_action", ""),
    }
