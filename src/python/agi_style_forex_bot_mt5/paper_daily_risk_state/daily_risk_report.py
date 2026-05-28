"""Reports and CLI helpers for daily paper risk state."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .daily_risk_ledger import append_daily_risk_clearance
from .daily_window import current_operational_day
from .drawdown_state_classifier import classify_drawdown_halts
from .drawdown_state_loader import load_drawdown_state
from .micro_drawdown_guard import validate_micro_daily_risk


def run_paper_daily_risk_audit(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    clearance_ledger: str | Path | None = None,
    daily_risk_ledger: str | Path | None = None,
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/paper_daily_risk",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    from agi_style_forex_bot_mt5.paper_trading.paper_pnl_engine import pnl_value

    state = load_drawdown_state(
        database=database,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=paper_risk_dir,
        clearance_ledger=clearance_ledger,
        profile_config=profile_config,
    )
    classified = classify_drawdown_halts(
        halt_events=list(state.get("halt_events", [])),
        profile_clearance=dict(state.get("profile_clearance", {})),
        daily_risk_ledger=str(daily_risk_ledger) if daily_risk_ledger else None,
        profile_config=str(profile_config) if profile_config else None,
        pnl_audit_dir=str(Path(reports_root) / "paper_pnl_audit"),
    )
    guard = validate_micro_daily_risk(
        database=database,
        clearance_ledger=clearance_ledger,
        daily_risk_ledger=daily_risk_ledger,
        profile_config=profile_config,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=paper_risk_dir,
    )
    summary = {
        "mode": "paper-daily-risk-audit",
        "paper_daily_risk_status": _audit_status(guard, classified),
        "active_today_halt_count": classified.get("active_today_halt_count", 0),
        "legacy_quarantined_halt_count": classified.get("legacy_quarantined_halt_count", 0),
        "stale_halt_count": classified.get("stale_halt_count", 0),
        "invalid_timestamp_halt_count": classified.get("invalid_timestamp_halt_count", 0),
        "unknown_review_required_count": classified.get("unknown_review_required_count", classified.get("unknown_halt_count", 0)),
        "unknown_halt_count": classified.get("unknown_halt_count", 0),
        "latest_clearance_utc": classified.get("latest_clearance_utc", ""),
        "latest_halt_utc": classified.get("latest_halt_utc", ""),
        "latest_halt_after_clearance": classified.get("latest_halt_after_clearance", False),
        "daily_risk_ledger_status": classified.get("daily_risk_ledger_status", ""),
        "can_resume_micro_shadow": guard.get("accepted", False),
        "blocking_reason": "" if guard.get("accepted") else guard.get("blocking_reason", ""),
        "active_scaled_drawdown": classified.get("active_scaled_drawdown_count", 0),
        "legacy_unscaled_drawdown": classified.get("legacy_quarantined_halt_count", 0),
        "drawdown_basis": classified.get("drawdown_basis", "SCALED_PAPER_PNL_ONLY"),
        "legacy_drawdown_quarantined": classified.get("legacy_drawdown_quarantined", False),
        "paper_trades_open": state.get("paper_trades_open", 0),
        "raw_daily_pnl": sum(float(trade.get("raw_pnl", trade.get("profit", 0.0)) or 0.0) for trade in state.get("trades", [])),
        "scaled_daily_pnl": sum(pnl_value(trade) for trade in state.get("trades", [])),
        "drawdown_basis": "SCALED_PAPER_PNL",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, classified.get("halt_classifications", []), state.get("trades", []))
    summary["reports_created"] = [str(path) for path in paths]
    return summary


def run_paper_daily_risk_clear(
    *,
    database: TelemetryDatabase,
    reason: str,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    clearance_ledger: str | Path | None = None,
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/paper_daily_risk",
) -> dict[str, Any]:
    if not str(reason or "").strip():
        return _denied("PAPER_DAILY_RISK_CLEAR_DENIED_NO_REASON", "paper-daily-risk-clear requires --reason")
    state = load_drawdown_state(
        database=database,
        log_dir=log_dir,
        reports_root=reports_root,
        paper_risk_dir=paper_risk_dir,
        clearance_ledger=clearance_ledger,
        profile_config=profile_config,
    )
    classified = classify_drawdown_halts(
        halt_events=list(state.get("halt_events", [])),
        profile_clearance=dict(state.get("profile_clearance", {})),
        daily_risk_ledger=None,
        profile_config=str(profile_config) if profile_config else None,
        pnl_audit_dir=str(Path(reports_root) / "paper_pnl_audit"),
    )
    validation = dict(state.get("profile_clearance_validation", {}))
    if int(state.get("paper_trades_open", 0) or 0) > 0:
        return _denied("PAPER_DAILY_RISK_CLEAR_DENIED_OPEN_TRADES", "Open paper trades must be zero.")
    if not validation.get("accepted"):
        return _denied("PAPER_DAILY_RISK_CLEAR_DENIED_CLEARANCE", str(validation.get("reason") or "Valid micro clearance is required."))
    if not state.get("execution_evidence_clear", False):
        return _denied("PAPER_DAILY_RISK_CLEAR_DENIED_EXECUTION_EVIDENCE", "Execution evidence must be clear.")
    if not state.get("telemetry_clear", False):
        return _denied("PAPER_DAILY_RISK_CLEAR_DENIED_TELEMETRY", "Telemetry must be clear or quarantined.")
    if classified.get("active_today_halt_count", 0) or classified.get("active_scaled_drawdown_count", 0):
        return _denied("PAPER_DAILY_RISK_CLEAR_DENIED_ACTIVE_HALT", "A halt after the latest clearance cannot be cleared as stale.")
    entry = append_daily_risk_clearance(
        output_dir=output_dir,
        reason=reason,
        latest_halt_utc=str(classified.get("latest_halt_utc", "")),
        latest_clearance_utc=str(validation.get("clearance", {}).get("created_at_utc") or classified.get("latest_clearance_utc", "")),
        clearance_id=str(validation.get("paper_risk_clearance_id", "")),
        operational_day=current_operational_day(),
    )
    summary = {
        "mode": "paper-daily-risk-clear",
        "paper_daily_risk_clearance_status": "PAPER_DAILY_RISK_CLEARANCE_GRANTED",
        "classification": "PAPER_DAILY_RISK_CLEARANCE_GRANTED",
        "cleared_for_profile": "BALANCED_STABLE_MICRO",
        "stale_halts_cleared": True,
        "legacy_drawdown_quarantined": bool(classified.get("legacy_drawdown_quarantined", False) or classified.get("legacy_quarantined_halt_count", 0) or classified.get("stale_halt_count", 0)),
        "active_halts_cleared": False,
        "can_resume_micro_shadow": True,
        "not_for_demo_live": True,
        "daily_risk_clearance_id": entry["daily_risk_clearance_id"],
        "ledger_path": entry["ledger_path"],
        "reason": reason,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = Path(output_dir) / "paper_daily_risk_clear_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path), entry["ledger_path"]]
    return summary


def _audit_status(guard: Mapping[str, Any], classified: Mapping[str, Any]) -> str:
    if guard.get("accepted"):
        if classified.get("legacy_drawdown_quarantined"):
            return "LEGACY_DRAWDOWN_QUARANTINED"
        return "PAPER_DAILY_RISK_CLEAR"
    if classified.get("active_today_halt_count", 0):
        return "ACTIVE_DRAWDOWN_HALT"
    if classified.get("stale_halt_count", 0):
        return "PAPER_DAILY_RISK_STALE_HALT_REVIEW_REQUIRED"
    if classified.get("invalid_timestamp_halt_count", 0) or classified.get("unknown_halt_count", 0):
        return "PAPER_DAILY_RISK_REVIEW_REQUIRED"
    return "PAPER_DAILY_RISK_BLOCKED"


def _write_reports(output: Path, summary: Mapping[str, Any], classifications: list[Mapping[str, Any]], trades: list[Mapping[str, Any]]) -> list[Path]:
    summary_path = output / "paper_daily_risk_summary.json"
    halt_path = output / "drawdown_halt_classification.csv"
    symbol_path = output / "daily_pnl_by_symbol.csv"
    strategy_path = output / "daily_pnl_by_strategy.csv"
    html_path = output / "report.html"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(halt_path, classifications)
    _write_csv(symbol_path, _aggregate(trades, "symbol"))
    _write_csv(strategy_path, _aggregate(trades, "strategy_name"))
    html_path.write_text(f"<html><body><h1>Paper Daily Risk</h1><pre>{html.escape(json.dumps(summary, indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return [summary_path, halt_path, symbol_path, strategy_path, html_path]


def _aggregate(trades: list[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    from agi_style_forex_bot_mt5.paper_trading.paper_pnl_engine import pnl_value

    rows: dict[str, dict[str, Any]] = {}
    for trade in trades:
        name = str(trade.get(key) or "UNKNOWN")
        row = rows.setdefault(name, {key: name, "trades": 0, "paper_pnl": 0.0, "execution_attempted": False})
        row["trades"] += 1
        row["paper_pnl"] += pnl_value(trade)
    return list(rows.values())


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    keys = sorted({key for row in rows for key in row.keys()} | {"execution_attempted"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key == "execution_attempted" else "") for key in keys})


def _denied(classification: str, reason: str) -> dict[str, Any]:
    return {
        "mode": "paper-daily-risk-clear",
        "paper_daily_risk_clearance_status": classification,
        "classification": classification,
        "reason": reason,
        "can_resume_micro_shadow": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
