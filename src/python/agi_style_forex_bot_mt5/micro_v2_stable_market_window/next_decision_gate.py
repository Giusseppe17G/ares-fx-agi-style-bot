"""Decision gate for Micro V2 stable market window."""

from __future__ import annotations

from typing import Any, Mapping


def decide_stable_market_window(
    *,
    dataset: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
    coverage: Mapping[str, Any],
    market: Mapping[str, Any],
    trade: Mapping[str, Any],
    filter_analysis: Mapping[str, Any],
) -> dict[str, Any]:
    if _safety(dataset):
        return _decision("MICRO_V2_SAFETY_BLOCKED", "STOP_AND_REVIEW_EXECUTION_SAFETY_EVIDENCE")
    if not heartbeat.get("v2_runtime_active"):
        return _decision("MICRO_V2_RUNTIME_NOT_RUNNING", "VERIFY_V2_RUNTIME_HEARTBEAT_WITHOUT_TOUCHING_STABLE")
    if not heartbeat.get("mt5_connected"):
        return _decision("MICRO_V2_MT5_DISCONNECTED", "RESTORE_MT5_CONNECTION_FOR_PAPER_OBSERVATION")
    coverage_ratio = float(coverage.get("fresh_tick_coverage_ratio", 0.0) or 0.0)
    stable_coverage = coverage_ratio >= (2 / 3)
    closed = int(trade.get("paper_trades_closed", 0) or 0)
    hours = float(heartbeat.get("observed_market_open_hours", 0.0) or 0.0)
    rejection_rate = float(trade.get("rejection_rate", 0.0) or 0.0)
    real_filter_dominant = bool(filter_analysis.get("dominant_v2_filter")) and str(filter_analysis.get("dominant_v2_filter")) not in {"", "MARKET_CLOSED", "STALE_TICK"}
    if market.get("market_closed_dominance_ratio", 0.0) > 0.5:
        return _decision("MICRO_V2_MARKET_WINDOW_NOT_STABLE", "CONTINUE_V2_AND_RERUN_CHECKPOINT_READINESS_LATER")
    if closed >= 10 and hours >= 24:
        return _decision("MICRO_V2_READY_FOR_ACCEPTANCE_EVIDENCE_PACK", "PREPARE_V2_ACCEPTANCE_EVIDENCE_PACK")
    if closed > 0 and not stable_coverage:
        return _decision("MICRO_V2_READY_FOR_TRADE_FREQUENCY_LIFECYCLE_AUDIT", "PREPARE_COMBINED_FREQUENCY_LIFECYCLE_PNL_AUDIT")
    if coverage_ratio > 0 and not stable_coverage:
        return _decision("MICRO_V2_MARKET_WINDOW_PARTIALLY_STABLE", "WAIT_FOR_MORE_SYMBOLS_WITH_FRESH_TICKS")
    if stable_coverage and 1 <= closed < 10:
        return _decision("MICRO_V2_MARKET_WINDOW_STABLE_COLLECTING_TRADES", "KEEP_MONITORING_V2_UNTIL_10_CLOSED_PAPER_TRADES")
    if stable_coverage and closed == 0 and rejection_rate >= 0.8 and real_filter_dominant:
        return _decision("MICRO_V2_READY_FOR_FILTER_TUNING_REVIEW", "PREPARE_FILTER_TUNING_REVIEW_WITHOUT_RUNTIME_CHANGE")
    if stable_coverage and closed == 0:
        return _decision("MICRO_V2_MARKET_WINDOW_STABLE_NO_TRADES_YET", "RUN_MICRO_V2_FILTER_ANALYSIS_AND_KEEP_OBSERVING")
    return _decision("MICRO_V2_REQUIRES_MANUAL_REVIEW", "REVIEW_STABLE_WINDOW_PACK")


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
        "micro_v2_stable_market_window_status": status,
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
