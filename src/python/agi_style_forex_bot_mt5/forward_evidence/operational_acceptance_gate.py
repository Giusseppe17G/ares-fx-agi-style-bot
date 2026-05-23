"""Operational acceptance gate for BALANCED_STABLE forward evidence."""

from __future__ import annotations

from typing import Any, Mapping


def decide_operational_acceptance(
    *,
    evidence: Mapping[str, Any],
    metrics: Mapping[str, Any],
    drift: Mapping[str, Any],
    paper_audit: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a conservative operational decision for paper/shadow continuation."""

    if bool(evidence.get("execution_attempted")) or bool(evidence.get("order_send_called")) or bool(evidence.get("order_check_called")):
        return _decision("PAUSE_FORWARD_SHADOW", "Execution path was attempted or broker order function appeared in evidence.")
    if str(metrics.get("paper_drawdown_status", "")) == "PAPER_DAILY_DRAWDOWN":
        return _decision("PAUSE_FORWARD_SHADOW", "Paper daily drawdown halt is active.")
    if int(evidence.get("invalid_timestamp_count", 0) or 0) > 0:
        return _decision("NEEDS_TELEMETRY_FIX", "Forward evidence contains invalid or redacted timestamps.")
    if not bool(evidence.get("stable_gate_confirmed")):
        return _decision("PAUSE_FORWARD_SHADOW", "Stable gate is missing.")
    if int(evidence.get("heartbeat_count", 0) or 0) == 0:
        return _decision("PAUSE_FORWARD_SHADOW", "Missing heartbeat evidence.")
    if str(paper_audit.get("status")) != "OK":
        return _decision("PAUSE_FORWARD_SHADOW", "Paper trade audit failed.")
    if str(drift.get("classification")) == "CRITICAL_DRIFT":
        return _decision("PAUSE_FORWARD_SHADOW", "Critical forward drift detected.")
    if float(evidence.get("hours_observed", 0.0) or 0.0) < 24 or int(metrics.get("closed_trades", 0) or 0) < 10:
        return _decision("NEEDS_MORE_FORWARD_DATA", "Forward observation has no critical issues but needs at least 24 hours and 10 closed paper trades.")
    if str(drift.get("classification")) == "WATCHLIST_DRIFT":
        return _decision("NEEDS_STABILITY_REPAIR", "Watchlist drift requires stability review before extended continuation.")
    return _decision("CONTINUE_FORWARD_SHADOW", "Forward evidence is healthy enough to continue paper/shadow observation.")


def _decision(decision: str, reason: str) -> dict[str, Any]:
    return {"mode": "forward-acceptance", "classification": decision, "decision": decision, "reason": reason, "execution_attempted": False}
