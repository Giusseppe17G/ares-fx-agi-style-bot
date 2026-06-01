"""Trade readiness audit for Micro V2 stable market window."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.v2_activity_audit import audit_activity


def audit_trade_readiness(dataset: Mapping[str, Any], checkpoint: Mapping[str, Any], filter_analysis: Mapping[str, Any]) -> dict[str, Any]:
    activity = audit_activity(dataset)
    open_trades = int(activity.get("paper_trades_open", checkpoint.get("v2_paper_trades_open", 0)) or 0)
    closed = int(activity.get("paper_trades_closed", checkpoint.get("v2_paper_trades_closed", 0)) or 0)
    closed_today = int(activity.get("paper_trades_closed_today", 0) or 0)
    signals = int(activity.get("signals_detected", filter_analysis.get("total_v2_signals", checkpoint.get("v2_signals_detected", 0))) or 0)
    rejected = int(activity.get("signals_rejected", filter_analysis.get("total_v2_rejections", checkpoint.get("v2_signals_rejected", 0))) or 0)
    accepted = max(signals - rejected, 0)
    status = "NO_TRADES_YET"
    if closed >= 10:
        status = "ENOUGH_TRADES_FOR_ACCEPTANCE_REVIEW"
    elif closed > 0:
        status = "COLLECTING_CLOSED_TRADES"
    elif open_trades > 0:
        status = "OPEN_TRADES_ACTIVE"
    elif accepted > 0:
        status = "ACCEPTED_SIGNALS_NO_CLOSED_TRADES"
    return {
        "trade_readiness_status": status,
        "paper_trades_open": open_trades,
        "paper_trades_closed": closed,
        "paper_trades_closed_today": closed_today,
        "signals_detected": signals,
        "signals_rejected": rejected,
        "accepted_signals": accepted,
        "rejection_rate": round(rejected / signals, 4) if signals else 0.0,
        "paper_trade_open_attempts": sum(1 for event in dataset.get("events", []) if str(event.get("event_type", "")).upper() == "PAPER_TRADE_OPENED"),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
