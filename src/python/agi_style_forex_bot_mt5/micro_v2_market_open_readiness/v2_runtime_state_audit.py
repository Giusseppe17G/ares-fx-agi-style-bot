"""V2 runtime activity and safety state for market-open readiness."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.heartbeat_audit import audit_heartbeat
from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.safety_status_audit import audit_safety_status
from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.v2_activity_audit import audit_activity


def audit_v2_runtime_state(dataset: Mapping[str, Any], monitor: Mapping[str, Any]) -> dict[str, Any]:
    heartbeat = audit_heartbeat(dataset)
    activity = audit_activity(dataset)
    safety = audit_safety_status(dataset)
    return {
        "v2_runtime_active": bool(heartbeat.get("process_appears_active", False)),
        "heartbeat_recent": bool(heartbeat.get("heartbeat_recent", False)),
        "heartbeat_stale": bool(heartbeat.get("heartbeat_stale", False)),
        "last_heartbeat_utc": heartbeat.get("latest_heartbeat_utc") or monitor.get("latest_heartbeat_utc"),
        "heartbeat_age_seconds": heartbeat.get("heartbeat_age_seconds"),
        "signals_detected": activity.get("signals_detected", monitor.get("v2_signals_detected", 0)),
        "signals_rejected": activity.get("signals_rejected", 0),
        "paper_trades_open": activity.get("paper_trades_open", monitor.get("v2_paper_trades_open", 0)),
        "paper_trades_closed": activity.get("paper_trades_closed", monitor.get("v2_paper_trades_closed", 0)),
        "safety_status": safety.get("safety_status", ""),
        "execution_attempted_detected": safety.get("execution_attempted_detected", False),
        "order_send_detected": safety.get("order_send_detected", False),
        "order_check_detected": safety.get("order_check_detected", False),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
