"""Paper state error and drawdown halt root-cause audit."""

from __future__ import annotations

from typing import Any, Mapping

from .drawdown_halt_loader import drawdown_halt_events


def audit_paper_state_error(dataset: Mapping[str, Any], closed_audit: Mapping[str, Any], open_audit: Mapping[str, Any], ledger_audit: Mapping[str, Any]) -> dict[str, Any]:
    events = list(dataset.get("events", []))
    halts = drawdown_halt_events(dict(dataset))
    critical_errors = [event for event in events if str(event.get("event_type", "")).upper() == "FORWARD_SHADOW_CRITICAL_ERROR"]
    latest_error = ""
    if critical_errors:
        payload = critical_errors[-1].get("payload") if isinstance(critical_errors[-1].get("payload"), Mapping) else {}
        latest_error = str(payload.get("error") or critical_errors[-1].get("message") or "")
    scaled_pnl = float(closed_audit.get("closed_scaled_pnl_total", 0.0) or 0.0)
    root_cause = "NO_DRAWDOWN_HALT_DETECTED"
    if open_audit.get("open_trade_integrity_status") != "OPEN_TRADE_INTEGRITY_OK":
        root_cause = "OPEN_TRADE_INTEGRITY_ISSUE"
    elif closed_audit.get("closed_trade_integrity_status") != "CLOSED_TRADE_INTEGRITY_OK":
        root_cause = "CLOSED_TRADE_INTEGRITY_ISSUE"
    elif scaled_pnl < 0 and halts:
        root_cause = "LEGITIMATE_CLOSED_PAPER_LOSS_DRAWDOWN"
    elif ledger_audit.get("ledger_scope_mismatch"):
        root_cause = "DAILY_RISK_LEDGER_SCOPE_MISMATCH"
    return {
        "paper_state_error_status": "PAPER_STATE_ERROR_ACTIVE" if latest_error or halts else "PAPER_STATE_ERROR_NOT_ACTIVE",
        "drawdown_halt_event_count": len(halts),
        "latest_critical_error": latest_error,
        "drawdown_halt_root_cause": root_cause,
        "closed_scaled_pnl_total": scaled_pnl,
        "paper_state_error_detected": bool(latest_error),
        "paper_daily_drawdown_halt_detected": bool(halts),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
