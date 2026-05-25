"""Fail-closed guard for BALANCED_STABLE_MICRO daily drawdown state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .drawdown_state_classifier import classify_drawdown_halts
from .drawdown_state_loader import load_drawdown_state


def validate_micro_daily_risk(
    *,
    database: TelemetryDatabase,
    clearance_ledger: str | Path | None,
    daily_risk_ledger: str | Path | None,
    profile_config: str | Path | None = None,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
) -> dict[str, Any]:
    state = load_drawdown_state(
        database=database,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=paper_risk_dir,
        clearance_ledger=clearance_ledger,
        profile_config=profile_config,
    )
    profile_validation = dict(state.get("profile_clearance_validation", {}))
    classified = classify_drawdown_halts(
        halt_events=list(state.get("halt_events", [])),
        profile_clearance=dict(state.get("profile_clearance", {})),
        daily_risk_ledger=str(daily_risk_ledger) if daily_risk_ledger else None,
        profile_config=str(profile_config) if profile_config else None,
    )
    if not profile_validation.get("accepted"):
        return _result(False, "PAPER_RISK_CLEARANCE_REQUIRED", str(profile_validation.get("reason") or "Valid micro clearance is required."), classified)
    if int(state.get("paper_trades_open", 0) or 0) > 0:
        return _result(False, "PAPER_DAILY_RISK_BLOCKED_OPEN_TRADES", "Open paper trades must be zero before clearing stale daily risk.", classified)
    if classified.get("active_today_halt_count", 0):
        return _result(False, "PAPER_DRAWDOWN_HALT_BLOCK", "A paper drawdown halt exists after clearance.", classified)
    if classified.get("unknown_halt_count", 0):
        return _result(False, "PAPER_DAILY_RISK_REVIEW_REQUIRED", "Unknown drawdown halt timestamps require review.", classified)
    if classified.get("stale_halt_count", 0) and classified.get("daily_risk_ledger_status") != "DAILY_RISK_LEDGER_ACCEPTED":
        return _result(False, "PAPER_DAILY_RISK_LEDGER_REQUIRED", "Historical paper drawdown halts require daily risk ledger clearance.", classified)
    return {
        **_result(True, "PAPER_DAILY_RISK_ACCEPTED", "Daily paper risk state is clear for BALANCED_STABLE_MICRO paper/shadow.", classified),
        "paper_daily_risk_status": "PAPER_DAILY_RISK_CLEAR",
        "can_resume_micro_shadow": True,
        "cleared_for_profile": "BALANCED_STABLE_MICRO",
        "not_for_demo_live": True,
    }


def _result(accepted: bool, status: str, reason: str, classified: dict[str, Any]) -> dict[str, Any]:
    return {
        "accepted": accepted,
        "paper_daily_risk_status": status,
        "classification": status,
        "reason": reason,
        "blocking_reason": "" if accepted else status,
        "can_resume_micro_shadow": accepted,
        "active_today_halt_count": classified.get("active_today_halt_count", 0),
        "stale_halt_count": classified.get("stale_halt_count", 0),
        "invalid_timestamp_halt_count": classified.get("invalid_timestamp_halt_count", 0),
        "unknown_halt_count": classified.get("unknown_halt_count", 0),
        "latest_clearance_utc": classified.get("latest_clearance_utc", ""),
        "latest_halt_utc": classified.get("latest_halt_utc", ""),
        "latest_halt_after_clearance": classified.get("latest_halt_after_clearance", False),
        "daily_risk_ledger_status": classified.get("daily_risk_ledger_status", ""),
        "daily_risk_clearance_id": classified.get("daily_risk_clearance_id", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
