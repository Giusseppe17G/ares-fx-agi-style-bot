"""Dry-run monitor snapshot for Micro V2 checkpoints."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.base_vs_v2_comparator import compare_base_vs_v2
from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.heartbeat_audit import audit_heartbeat
from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.v2_activity_audit import audit_activity


def build_monitor_snapshot(base_dataset: Mapping[str, Any], v2_dataset: Mapping[str, Any], existing_monitor: Mapping[str, Any]) -> dict[str, Any]:
    base_heartbeat = audit_heartbeat(base_dataset)
    v2_heartbeat = audit_heartbeat(v2_dataset)
    base_activity = audit_activity(base_dataset)
    v2_activity = audit_activity(v2_dataset)
    comparison = compare_base_vs_v2(
        base_activity=base_activity,
        base_window=base_heartbeat,
        v2_activity=v2_activity,
        v2_window=v2_heartbeat,
    )
    return {
        "monitor_status": existing_monitor.get("micro_v2_dry_run_monitor_status", ""),
        "v2_signals_detected": v2_activity.get("signals_detected", 0),
        "v2_signals_rejected": v2_activity.get("signals_rejected", 0),
        "v2_rejection_rate": v2_activity.get("rejection_rate", 0.0),
        "v2_paper_trades_open": v2_activity.get("paper_trades_open", 0),
        "v2_paper_trades_closed": v2_activity.get("paper_trades_closed", 0),
        "v2_closed_trade_rate_per_24h": comparison.get("v2_metrics", {}).get("closed_trade_rate_per_24h", 0.0),
        "base_closed_trade_rate_per_24h": comparison.get("base_metrics", {}).get("closed_trade_rate_per_24h", 0.0),
        "paper_state_recovery_status": v2_activity.get("paper_state_recovery_status", ""),
        "config_error_root_cause": v2_activity.get("config_error_root_cause", ""),
        "v2_hours_observed": v2_heartbeat.get("hours_observed", 0.0),
        "top_rejection_reasons": v2_activity.get("rejected_by_reason", [])[:10],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
