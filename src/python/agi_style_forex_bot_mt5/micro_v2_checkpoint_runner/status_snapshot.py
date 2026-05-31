"""Runtime status snapshot for Micro V2 checkpoints."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.heartbeat_audit import audit_heartbeat
from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.safety_status_audit import audit_safety_status


def build_status_snapshot(base_dataset: Mapping[str, Any], v2_dataset: Mapping[str, Any]) -> dict[str, Any]:
    heartbeat = audit_heartbeat(v2_dataset)
    safety = audit_safety_status(base_dataset, v2_dataset)
    return {
        "v2_runtime_active": bool(heartbeat.get("process_appears_active", False)),
        "last_heartbeat_utc": heartbeat.get("latest_heartbeat_utc"),
        "heartbeat_recent": heartbeat.get("heartbeat_recent", False),
        "heartbeat_stale": heartbeat.get("heartbeat_stale", False),
        "v2_hours_observed": heartbeat.get("hours_observed", 0.0),
        "safety_status": safety.get("safety_status", ""),
        "execution_attempted_detected": safety.get("execution_attempted_detected", False),
        "order_send_detected": safety.get("order_send_detected", False),
        "order_check_detected": safety.get("order_check_detected", False),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
