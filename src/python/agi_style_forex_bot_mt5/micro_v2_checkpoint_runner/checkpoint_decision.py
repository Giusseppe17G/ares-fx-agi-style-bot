"""Checkpoint decision policy for Micro V2 observation."""

from __future__ import annotations

from typing import Any, Mapping


def decide_checkpoint(
    *,
    status: Mapping[str, Any],
    readiness: Mapping[str, Any],
    monitor: Mapping[str, Any],
) -> dict[str, Any]:
    safety_blocked = bool(status.get("execution_attempted_detected") or status.get("order_send_detected") or status.get("order_check_detected"))
    runtime_active = bool(status.get("v2_runtime_active") and not status.get("heartbeat_stale"))
    fresh_symbols = list(readiness.get("fresh_tick_symbols", []) or [])
    market_closed_dominant = bool(readiness.get("market_closed_rejection_dominant"))
    closed = int(monitor.get("v2_paper_trades_closed", 0) or 0)
    hours = float(monitor.get("v2_hours_observed", status.get("v2_hours_observed", 0.0)) or 0.0)
    rejection_rate = float(monitor.get("v2_rejection_rate", 0.0) or 0.0)
    trades_open = int(monitor.get("v2_paper_trades_open", 0) or 0)

    if safety_blocked:
        return _decision("MICRO_V2_CHECKPOINT_SAFETY_BLOCKED", "RUN_STOP_ROLLBACK_CHECKLIST_AND_REVIEW_SAFETY_EVIDENCE")
    if not runtime_active:
        return _decision("MICRO_V2_CHECKPOINT_RUNTIME_NOT_RUNNING", "VERIFY_OR_RESTART_V2_DRY_RUN_TERMINAL_WITHOUT_TOUCHING_STABLE")
    if not fresh_symbols and market_closed_dominant:
        return _decision("MICRO_V2_CHECKPOINT_WAITING_FOR_MARKET_OPEN", "RUN_MICRO_V2_MARKET_OPEN_READINESS_AGAIN_WHEN_MARKET_OPENS")
    if closed >= 10 and hours >= 24:
        return _decision("MICRO_V2_CHECKPOINT_READY_FOR_ACCEPTANCE_REVIEW", "PREPARE_SEPARATE_V2_ACCEPTANCE_REVIEW_PHASE")
    if 0 < closed < 10:
        return _decision("MICRO_V2_CHECKPOINT_NEEDS_MORE_TRADES", "KEEP_COLLECTING_V2_DATA_AND_MONITOR_CLOSED_TRADES")
    if fresh_symbols and closed == 0 and rejection_rate >= 0.8:
        return _decision("MICRO_V2_CHECKPOINT_READY_FOR_FILTER_ANALYSIS", "PREPARE_FUTURE_V2_FILTER_ANALYSIS_PHASE")
    if fresh_symbols and closed < 10:
        return _decision("MICRO_V2_CHECKPOINT_COLLECTING_FRESH_TICK_DATA", "KEEP_RUNNING_V2_PAPER_OBSERVATION_AND_REPEAT_CHECKPOINTS")
    if trades_open > 0:
        return _decision("MICRO_V2_CHECKPOINT_COLLECTING_FRESH_TICK_DATA", "MONITOR_OPEN_PAPER_TRADE_AND_REPEAT_CHECKPOINTS")
    return _decision("MICRO_V2_CHECKPOINT_REQUIRES_MANUAL_REVIEW", "REVIEW_V2_RUNTIME_READINESS_MONITOR_AND_REJECTION_REPORTS")


def _decision(status: str, action: str) -> dict[str, Any]:
    return {
        "micro_v2_checkpoint_status": status,
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
