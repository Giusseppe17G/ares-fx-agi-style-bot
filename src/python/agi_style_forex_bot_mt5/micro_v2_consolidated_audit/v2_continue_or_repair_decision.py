"""Consolidated continue-or-repair decision policy."""

from __future__ import annotations

from typing import Any, Mapping


def decide_continue_or_repair(
    *,
    dataset: Mapping[str, Any],
    exposure: Mapping[str, Any],
    double_counting: Mapping[str, Any],
    market: Mapping[str, Any],
    risk: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    if _safety(dataset):
        return _decision("MICRO_V2_SAFETY_BLOCKED", "STOP_AND_REVIEW_EXECUTION_SAFETY_EVIDENCE")
    if market.get("market_closed_dominance_ratio", 0.0) > 0.5:
        return _decision("MICRO_V2_MARKET_NOT_STABLE_ENOUGH", "CONTINUE_COLLECTING_MARKET_OPEN_DATA_BEFORE_TUNING")
    if double_counting.get("double_counting_detected"):
        return _decision("MICRO_V2_EXPOSURE_POSSIBLE_DOUBLE_COUNTING", "PLAN_RUNTIME_REPAIR_REVIEW_FOR_EXPOSURE_DOUBLE_COUNTING")
    if exposure.get("exposure_data_missing"):
        return _decision("MICRO_V2_EXPOSURE_DATA_MISSING", "PLAN_RUNTIME_REPAIR_REVIEW_FOR_EXPOSURE_TELEMETRY")
    if exposure.get("profile_parse_error"):
        return _decision("MICRO_V2_EXPOSURE_PROFILE_PARSE_ERROR", "REVIEW_V2_PROFILE_EXPOSURE_LIMIT_FIELDS_OFFLINE")
    if int(checkpoint.get("v2_paper_trades_closed", 0) or 0) > 0 or int(checkpoint.get("v2_signals_accepted", 0) or 0) > 0:
        return _decision("MICRO_V2_READY_FOR_TRADE_FREQUENCY_REEVALUATION", "RUN_FUTURE_TRADE_FREQUENCY_REEVALUATION_PHASE")
    if risk.get("risk_guard_expected") and market.get("market_stability_status") == "MARKET_STABLE_ENOUGH_FOR_FILTER_ANALYSIS":
        return _decision("MICRO_V2_CONTINUE_COLLECTING_MARKET_DATA", "KEEP_V2_RUNNING_IN_PAPER_SHADOW_AND_REPEAT_CHECKPOINTS")
    if risk.get("dominant_risk_block_reason") and market.get("fresh_tick_symbols"):
        return _decision("MICRO_V2_READY_FOR_FILTER_TUNING_REVIEW", "PREPARE_FUTURE_FILTER_TUNING_REVIEW_WITH_NO_RUNTIME_CHANGE")
    return _decision("MICRO_V2_REQUIRES_MANUAL_REVIEW", "REVIEW_CONSOLIDATED_AUDIT_REPORTS")


def _safety(dataset: Mapping[str, Any]) -> bool:
    for row in [*dataset.get("events", []), *dataset.get("heartbeats", []), *dataset.get("paper_trades", [])]:
        payload = row.get("payload", {}) if isinstance(row.get("payload"), Mapping) else {}
        if row.get("execution_attempted") or row.get("order_send_called") or row.get("order_check_called"):
            return True
        if payload.get("execution_attempted") or payload.get("order_send_called") or payload.get("order_check_called"):
            return True
    return False


def _decision(status: str, action: str) -> dict[str, Any]:
    return {
        "consolidated_v2_audit_status": status,
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
