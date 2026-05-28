"""Paper state recovery audit and paper-only stale trade close helpers."""

from __future__ import annotations

import configparser
import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.contracts import Environment, Event, Severity
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime

from .paper_pnl_engine import pnl_value

STALE_OPEN_TRADE_SECONDS = 24 * 60 * 60


def run_paper_state_recovery_audit(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    daily_risk_dir: str | Path = "data/reports/paper_daily_risk",
    pnl_audit_dir: str | Path = "data/reports/paper_pnl_audit",
    clearance_ledger: str | Path | None = None,
    daily_risk_ledger: str | Path | None = None,
    profile_config: str | Path | None = None,
    stable_gate: str | Path | None = None,
    output_dir: str | Path = "data/reports/paper_state_recovery",
) -> dict[str, Any]:
    """Audit CONFIG_ERROR/PAPER_STATE_ERROR and open paper trades without mutation."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    state = database.get_operational_state()
    open_rows = [_payload(row) for row in database.fetch_open_paper_trades()]
    config = _audit_config(
        state=state,
        profile_config=profile_config,
        stable_gate=stable_gate,
        clearance_ledger=clearance_ledger,
        daily_risk_ledger=daily_risk_ledger,
        paper_risk_dir=paper_risk_dir,
        daily_risk_dir=daily_risk_dir,
        pnl_audit_dir=pnl_audit_dir,
    )
    config = _merge_root_cause_audit(config, Path(reports_root) / "config_error_recovery" / "config_error_root_cause_summary.json")
    trade_rows = [_audit_open_trade(row) for row in open_rows]
    stale_count = sum(1 for row in trade_rows if row["trade_audit_status"] == "STALE_OPEN_PAPER_TRADE")
    orphan_count = sum(1 for row in trade_rows if row["trade_audit_status"] == "ORPHAN_OPEN_PAPER_TRADE")
    invalid_risk_count = sum(1 for row in trade_rows if row["trade_audit_status"] == "INVALID_RISK_OPEN_PAPER_TRADE")
    valid_count = sum(1 for row in trade_rows if row["trade_audit_status"] == "VALID_OPEN_PAPER_TRADE")
    requires_close = stale_count > 0 or orphan_count > 0
    requires_review = bool(config["config_error_blocking"] or requires_close or invalid_risk_count > 0)
    recovery_status = "PAPER_STATE_RECOVERY_OK"
    if config["config_error_blocking"]:
        recovery_status = "PAPER_STATE_RECOVERY_CONFIG_BLOCKED"
    elif requires_close:
        recovery_status = "PAPER_STATE_RECOVERY_OPEN_TRADE_REVIEW"
    elif invalid_risk_count > 0:
        recovery_status = "PAPER_STATE_RECOVERY_OPEN_TRADE_REVIEW"
    elif valid_count > 0:
        recovery_status = "PAPER_STATE_RECOVERY_VALID_OPEN_TRADE"
    summary = {
        "mode": "paper-state-recovery-audit",
        "paper_state_recovery_status": recovery_status,
        "halt_reason": state.get("halt_reason") or state.get("paused_reason") or "",
        "latest_exit_reason": state.get("latest_exit_reason", ""),
        "paper_shadow_paused": bool(state.get("shadow_paused", False)),
        "paper_clean_state": len(open_rows) == 0 and not config["config_error_blocking"],
        "paper_state_clean_for_observation": not config["config_error_blocking"] and not requires_close and invalid_risk_count == 0,
        "recovery_required": requires_review,
        "recovery_recommended_action": _recommended_action(config, stale_count, orphan_count, invalid_risk_count, valid_count),
        **config,
        "open_paper_trades_count": len(open_rows),
        "open_trade_audit_status": _open_trade_audit_status(stale_count, orphan_count, invalid_risk_count, valid_count),
        "stale_open_trade_count": stale_count,
        "orphan_open_trade_count": orphan_count,
        "invalid_risk_open_trade_count": invalid_risk_count,
        "valid_open_trade_count": valid_count,
        "open_trade_age_seconds": max([float(row.get("open_trade_age_seconds") or 0.0) for row in trade_rows], default=0.0),
        "open_trade_symbol": trade_rows[0].get("symbol", "") if trade_rows else "",
        "open_trade_strategy": trade_rows[0].get("strategy_name", "") if trade_rows else "",
        "open_trade_unrealized_pnl": trade_rows[0].get("open_trade_unrealized_pnl", 0.0) if trade_rows else 0.0,
        "can_safely_continue_with_open_trade": valid_count == len(open_rows) and len(open_rows) > 0 and invalid_risk_count == 0 and not config["config_error_blocking"],
        "requires_paper_only_close": requires_close,
        "requires_manual_review": requires_review,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_recovery_reports(output, summary, trade_rows, config)
    summary["reports_created"] = [str(path) for path in paths]
    return summary


def run_paper_state_recovery_plan(
    *,
    audit_dir: str | Path = "data/reports/paper_state_recovery",
    output_dir: str | Path = "data/reports/paper_state_recovery",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    audit = _load_json(Path(audit_dir) / "paper_state_recovery_summary.json")
    decision = _plan_decision(audit)
    md = output / "PAPER_STATE_RECOVERY_PLAN.md"
    ps1 = output / "recovery_commands.ps1"
    md.write_text(_plan_markdown(audit, decision), encoding="utf-8")
    ps1.write_text(_plan_commands(decision), encoding="utf-8")
    return {
        "mode": "paper-state-recovery-plan",
        "recovery_plan_decision": decision,
        "reports_created": [str(md), str(ps1)],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def close_stale_open_paper_trade(
    *,
    database: TelemetryDatabase,
    reason: str,
    output_dir: str | Path,
    confirm_paper_only: bool = False,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    open_rows = [_payload(row) for row in database.fetch_open_paper_trades()]
    audited = [_audit_open_trade(row) for row in open_rows]
    closable_ids = {str(row.get("trade_id")) for row in audited if row.get("trade_audit_status") in {"STALE_OPEN_PAPER_TRADE", "ORPHAN_OPEN_PAPER_TRADE"}}
    if not reason:
        status = "PAPER_CLOSE_STALE_DENIED_NO_REASON"
    elif not confirm_paper_only:
        status = "PAPER_CLOSE_STALE_DRY_RUN"
    elif not closable_ids:
        status = "PAPER_CLOSE_STALE_DENIED_NOT_STALE"
    else:
        status = "PAPER_CLOSE_STALE_COMPLETED"
    closed: list[dict[str, Any]] = []
    if status == "PAPER_CLOSE_STALE_COMPLETED":
        now = datetime.now(timezone.utc).isoformat()
        for trade in open_rows:
            if str(trade.get("paper_trade_id")) not in closable_ids:
                continue
            payload = {
                **trade,
                "status": "CLOSED",
                "exit_time_utc": now,
                "exit_price": trade.get("exit_price") or trade.get("entry_price"),
                "exit_reason": "STALE_PAPER_ONLY_CLOSE",
                "close_reason": reason,
                "metadata": {**(trade.get("metadata") if isinstance(trade.get("metadata"), dict) else {}), "paper_state_recovery_close_reason": reason, "paper_only": True},
            }
            database.update_paper_trade(payload)
            database.insert_paper_trade_event(str(payload.get("paper_trade_id")), "PAPER_STALE_OPEN_TRADE_CLOSED", payload)
            _audit(database, "PAPER_STALE_OPEN_TRADE_CLOSED", Severity.WARNING, payload)
            closed.append(payload)
    summary = {
        "mode": "paper-close-stale-open-trade",
        "paper_close_status": status,
        "dry_run": not confirm_paper_only,
        "confirm_paper_only": bool(confirm_paper_only),
        "reason": reason,
        "open_paper_trades_found": len(open_rows),
        "closable_stale_or_orphan_count": len(closable_ids),
        "paper_trades_closed": len(closed),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = output / "paper_close_stale_open_trade_report.json"
    path.write_text(json.dumps(_jsonable({**summary, "closed_trades": closed, "audited_open_trades": audited}), indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path)]
    return summary


def run_invalid_open_paper_trade_audit(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/paper_state_recovery",
) -> dict[str, Any]:
    """Audit open paper trades that cannot be safely marked to market."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    open_rows = [_payload(row) for row in database.fetch_open_paper_trades()]
    audited = [_invalid_trade_row(row) for row in open_rows]
    invalid_rows = [row for row in audited if row["is_invalid_open_trade"]]
    zero_risk = sum(1 for row in invalid_rows if row["zero_risk_distance"])
    missing_entry = sum(1 for row in invalid_rows if row["missing_entry_price"])
    missing_sl = sum(1 for row in invalid_rows if row["missing_sl_price"])
    invalid_direction = sum(1 for row in invalid_rows if row["invalid_direction"])
    classification = "NO_INVALID_OPEN_PAPER_TRADES"
    if invalid_rows:
        classification = "INVALID_OPEN_PAPER_TRADE_BLOCKING"
    if zero_risk:
        classification = "ZERO_RISK_OPEN_PAPER_TRADE_FOUND"
    summary = {
        "mode": "invalid-open-paper-trade-audit",
        "invalid_open_trade_status": classification,
        "invalid_open_trade_count": len(invalid_rows),
        "zero_risk_distance_count": zero_risk,
        "missing_entry_price_count": missing_entry,
        "missing_sl_price_count": missing_sl,
        "invalid_direction_count": invalid_direction,
        "affected_trade_ids": [row["trade_id"] for row in invalid_rows],
        "recommended_action": "Run paper-close-invalid-open-trade for each affected trade after manual review." if invalid_rows else "No invalid open paper trades found.",
        "log_dir": str(log_dir),
        "reports_root": str(reports_root),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_invalid_trade_audit_reports(output, summary, invalid_rows, audited)
    return {**summary, "reports_created": [str(path) for path in paths]}


def close_invalid_open_paper_trade(
    *,
    database: TelemetryDatabase,
    trade_id: str,
    reason: str,
    output_dir: str | Path,
    confirm_paper_only: bool = False,
) -> dict[str, Any]:
    """Close exactly one invalid open paper trade in SQLite only."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    open_rows = [_payload(row) for row in database.fetch_open_paper_trades()]
    selected = next((row for row in open_rows if str(row.get("paper_trade_id")) == str(trade_id)), None)
    audited = _invalid_trade_row(selected or {"paper_trade_id": trade_id}) if selected else {"trade_id": trade_id, "is_invalid_open_trade": False}
    if not trade_id:
        status = "PAPER_CLOSE_INVALID_DENIED_NO_TRADE_ID"
    elif not reason:
        status = "PAPER_CLOSE_INVALID_DENIED_NO_REASON"
    elif not confirm_paper_only:
        status = "PAPER_CLOSE_INVALID_DRY_RUN"
    elif selected is None:
        status = "PAPER_CLOSE_INVALID_DENIED_NOT_OPEN"
    elif not audited.get("is_invalid_open_trade"):
        status = "PAPER_CLOSE_INVALID_DENIED_TRADE_VALID"
    else:
        status = "PAPER_CLOSE_INVALID_COMPLETED"
    closed: dict[str, Any] = {}
    if status == "PAPER_CLOSE_INVALID_COMPLETED" and selected is not None:
        now = datetime.now(timezone.utc).isoformat()
        metadata = selected.get("metadata") if isinstance(selected.get("metadata"), dict) else {}
        closed = {
            **selected,
            "status": "CLOSED",
            "exit_time_utc": now,
            "exit_price": selected.get("exit_price") or selected.get("entry_price"),
            "exit_reason": "INVALID_OPEN_PAPER_TRADE_CLOSE",
            "close_reason": reason,
            "closed_by": "paper-close-invalid-open-trade",
            "invalid_close": True,
            "profit": float(selected.get("profit") or selected.get("scaled_paper_pnl") or 0.0),
            "r_multiple": float(selected.get("r_multiple") or 0.0),
            "metadata": {
                **metadata,
                "paper_state_recovery_close_reason": reason,
                "closed_by": "paper-close-invalid-open-trade",
                "invalid_close": True,
                "invalid_trade_audit": audited,
                "paper_only": True,
            },
        }
        database.update_paper_trade(closed)
        database.insert_paper_trade_event(str(closed.get("paper_trade_id")), "PAPER_INVALID_OPEN_TRADE_CLOSED", closed)
        _audit(database, "PAPER_INVALID_OPEN_TRADE_CLOSED", Severity.WARNING, closed)
        database.update_operational_state(
            {
                "latest_exit_reason": "",
                "halt_reason": "",
                "latest_forward_shadow_error": "",
                "config_error_resolved": True,
                "invalid_open_paper_trade_resolved": True,
                "paper_state_recovery_status": "PAPER_STATE_RECOVERY_CLEAR",
                "paper_state_recovery_resolved_at_utc": now,
            }
        )
    remaining_invalid = [_invalid_trade_row(row) for row in [_payload(item) for item in database.fetch_open_paper_trades()]]
    remaining_invalid_count = sum(1 for row in remaining_invalid if row.get("is_invalid_open_trade"))
    summary = {
        "mode": "paper-close-invalid-open-trade",
        "paper_close_invalid_status": status,
        "dry_run": not confirm_paper_only,
        "confirm_paper_only": bool(confirm_paper_only),
        "trade_id": trade_id,
        "reason": reason,
        "selected_trade_open": selected is not None,
        "selected_trade_invalid": bool(audited.get("is_invalid_open_trade")),
        "paper_trades_closed": 1 if closed else 0,
        "remaining_invalid_open_trade_count": remaining_invalid_count,
        "recovery_event": "PAPER_INVALID_OPEN_TRADE_CLOSED" if closed else "",
        "config_error_resolved": bool(closed and remaining_invalid_count == 0),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_invalid_close_reports(output, summary, audited, closed)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _audit_config(
    *,
    state: Mapping[str, Any],
    profile_config: str | Path | None,
    stable_gate: str | Path | None,
    clearance_ledger: str | Path | None,
    daily_risk_ledger: str | Path | None,
    paper_risk_dir: str | Path,
    daily_risk_dir: str | Path,
    pnl_audit_dir: str | Path,
) -> dict[str, Any]:
    checks = {
        "missing_profile_config": _missing(profile_config),
        "missing_stable_gate": _missing(stable_gate),
        "missing_paper_risk_clearance": _missing(clearance_ledger),
        "missing_daily_risk_ledger": _missing(daily_risk_ledger),
        "missing_paper_risk_dir": not Path(paper_risk_dir).exists(),
        "missing_daily_risk_dir": not Path(daily_risk_dir).exists(),
        "missing_pnl_audit_dir": not Path(pnl_audit_dir).exists(),
        "invalid_cli_args": False,
        "config_parse_error": False,
        "profile_mismatch": False,
        "stable_gate_not_accepted": False,
        "unknown_config_error": False,
    }
    if profile_config and Path(profile_config).exists():
        parsed = _parse_profile_config(Path(profile_config))
        checks["config_parse_error"] = bool(parsed.get("config_parse_error"))
        profile = str(parsed.get("profile") or parsed.get("paper_risk_profile") or "").upper()
        checks["profile_mismatch"] = bool(profile and profile != "BALANCED_STABLE_MICRO")
    if stable_gate and Path(stable_gate).exists():
        gate = _load_json(Path(stable_gate))
        checks["stable_gate_not_accepted"] = not (gate.get("stable_gate_decision") == "PAPER_SHADOW_READY" or bool(gate.get("paper_shadow_ready", False)))
    latest_exit = str(state.get("latest_exit_reason") or "")
    halt = str(state.get("halt_reason") or state.get("paused_reason") or "")
    detected = latest_exit == "CONFIG_ERROR" or halt == "PAPER_STATE_ERROR"
    known = [key for key, value in checks.items() if value and key != "unknown_config_error"]
    checks["unknown_config_error"] = bool(detected and not known)
    root = known[0] if known else ("unknown_config_error" if checks["unknown_config_error"] else "")
    return {
        "config_error_detected": detected,
        "config_error_root_cause": root,
        "config_error_blocking": detected and bool(root),
        "recommended_config_fix": _config_fix(root),
        **checks,
    }


def _audit_open_trade(trade: Mapping[str, Any]) -> dict[str, Any]:
    opened = safe_parse_datetime(trade.get("entry_time_utc"), field_name="entry_time_utc", source="paper-state-recovery")
    age = (datetime.now(timezone.utc) - opened.value).total_seconds() if opened.value else None
    missing_core = [key for key in ("paper_trade_id", "symbol", "entry_price", "sl_price", "tp_price", "strategy_name") if trade.get(key) in {None, ""}]
    stale = age is not None and age > STALE_OPEN_TRADE_SECONDS
    orphan = bool(missing_core or opened.value is None)
    invalid_risk = _invalid_risk_distance(trade)
    status = "VALID_OPEN_PAPER_TRADE"
    if orphan:
        status = "ORPHAN_OPEN_PAPER_TRADE"
    elif invalid_risk:
        status = "INVALID_RISK_OPEN_PAPER_TRADE"
    elif stale:
        status = "STALE_OPEN_PAPER_TRADE"
    return {
        "trade_id": trade.get("paper_trade_id", ""),
        "symbol": trade.get("symbol", ""),
        "strategy_name": trade.get("strategy_name", ""),
        "opened_at": trade.get("entry_time_utc", ""),
        "open_trade_age_seconds": age,
        "open_trade_unrealized_pnl": pnl_value(trade),
        "stop_loss": trade.get("sl_price", ""),
        "take_profit": trade.get("tp_price", ""),
        "missing_core_fields": ",".join(missing_core),
        "invalid_risk_distance": invalid_risk,
        "timestamp_parse_status": opened.status,
        "timestamp_warning": opened.warning,
        "trade_audit_status": status,
        "can_safely_continue_with_open_trade": status == "VALID_OPEN_PAPER_TRADE",
        "requires_paper_only_close": status in {"STALE_OPEN_PAPER_TRADE", "ORPHAN_OPEN_PAPER_TRADE"},
        "requires_manual_review": status != "VALID_OPEN_PAPER_TRADE",
        "execution_attempted": False,
    }


def _write_recovery_reports(output: Path, summary: Mapping[str, Any], trade_rows: list[Mapping[str, Any]], config: Mapping[str, Any]) -> list[Path]:
    summary_path = output / "paper_state_recovery_summary.json"
    events_path = output / "paper_state_recovery_events.csv"
    trades_path = output / "open_paper_trade_audit.csv"
    config_path = output / "config_error_audit.csv"
    html_path = output / "report.html"
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(events_path, [summary])
    _write_csv(trades_path, trade_rows)
    _write_csv(config_path, [config])
    html_path.write_text(f"<html><body><h1>Paper State Recovery</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return [summary_path, events_path, trades_path, config_path, html_path]


def _write_invalid_trade_audit_reports(output: Path, summary: Mapping[str, Any], invalid_rows: list[Mapping[str, Any]], audited_rows: list[Mapping[str, Any]]) -> list[Path]:
    summary_path = output / "invalid_open_paper_trade_audit_summary.json"
    invalid_path = output / "invalid_open_paper_trades.csv"
    events_path = output / "invalid_open_trade_events.csv"
    html_path = output / "report.html"
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(invalid_path, invalid_rows)
    _write_csv(events_path, audited_rows)
    html_path.write_text(f"<html><body><h1>Invalid Open Paper Trade Audit</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return [summary_path, invalid_path, events_path, html_path]


def _write_invalid_close_reports(output: Path, summary: Mapping[str, Any], audited: Mapping[str, Any], closed: Mapping[str, Any]) -> list[Path]:
    summary_path = output / "invalid_trade_close_summary.json"
    event_path = output / "invalid_trade_close_event.json"
    ledger_path = output / "invalid_trade_close_ledger.json"
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    event_path.write_text(json.dumps(_jsonable({"summary": summary, "audited_trade": audited, "closed_trade": closed, "execution_attempted": False, "order_send_called": False, "order_check_called": False}), indent=2, sort_keys=True), encoding="utf-8")
    ledger = _load_json(ledger_path)
    entries = ledger.get("invalid_open_trade_closures", []) if isinstance(ledger.get("invalid_open_trade_closures"), list) else []
    if closed:
        entries.append(
            {
                "trade_id": summary.get("trade_id"),
                "closed_at_utc": closed.get("exit_time_utc"),
                "reason": summary.get("reason"),
                "closed_by": "paper-close-invalid-open-trade",
                "invalid_close": True,
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    ledger_path.write_text(json.dumps(_jsonable({"mode": "invalid-trade-close-ledger", "invalid_open_trade_closures": entries, "execution_attempted": False, "order_send_called": False, "order_check_called": False}), indent=2, sort_keys=True), encoding="utf-8")
    return [summary_path, event_path, ledger_path]


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key == "execution_attempted" else "") for key in fieldnames})


def _invalid_trade_row(trade: Mapping[str, Any]) -> dict[str, Any]:
    entry = _float_or_none(trade.get("entry_price"))
    stop_loss = _float_or_none(trade.get("sl_price"))
    take_profit = _float_or_none(trade.get("tp_price"))
    direction = str(trade.get("direction") or "").upper()
    missing_entry = entry is None
    missing_sl = stop_loss is None
    risk_distance = None if entry is None or stop_loss is None else abs(entry - stop_loss)
    zero_risk = risk_distance is not None and risk_distance <= 0
    invalid_tp = take_profit is None
    invalid_direction = direction not in {"BUY", "SELL"}
    is_invalid = bool(missing_entry or missing_sl or zero_risk or invalid_tp or invalid_direction)
    reasons = []
    if missing_entry:
        reasons.append("MISSING_ENTRY_PRICE")
    if missing_sl:
        reasons.append("MISSING_SL_PRICE")
    if zero_risk:
        reasons.append("ZERO_RISK_DISTANCE")
    if invalid_tp:
        reasons.append("INVALID_TAKE_PROFIT")
    if invalid_direction:
        reasons.append("INVALID_DIRECTION")
    return {
        "trade_id": trade.get("paper_trade_id", ""),
        "symbol": trade.get("symbol", ""),
        "strategy_name": trade.get("strategy_name", ""),
        "entry_time_utc": trade.get("entry_time_utc", ""),
        "entry_price": trade.get("entry_price", ""),
        "sl_price": trade.get("sl_price", ""),
        "tp_price": trade.get("tp_price", ""),
        "direction": direction,
        "risk_distance": risk_distance,
        "missing_entry_price": missing_entry,
        "missing_sl_price": missing_sl,
        "zero_risk_distance": zero_risk,
        "invalid_take_profit": invalid_tp,
        "invalid_direction": invalid_direction,
        "is_invalid_open_trade": is_invalid,
        "invalid_reasons": ",".join(reasons),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _recommended_action(config: Mapping[str, Any], stale: int, orphan: int, invalid_risk: int, valid: int) -> str:
    if config.get("config_error_blocking"):
        return "FIX_CONFIG_AND_RERUN"
    if orphan > 0 or stale > 0:
        return "CLOSE_STALE_OPEN_PAPER_TRADE_PAPER_ONLY"
    if invalid_risk > 0:
        return "MANUAL_REVIEW_REQUIRED"
    if valid > 0:
        return "RESUME_WITH_VALID_OPEN_PAPER_TRADE"
    return "FIX_CONFIG_AND_RERUN" if config.get("config_error_detected") else "WAIT_FOR_TRADE_EXIT"


def _open_trade_audit_status(stale: int, orphan: int, invalid_risk: int, valid: int) -> str:
    if orphan > 0:
        return "ORPHAN_OPEN_PAPER_TRADE"
    if invalid_risk > 0:
        return "INVALID_RISK_OPEN_PAPER_TRADE"
    if stale > 0:
        return "STALE_OPEN_PAPER_TRADE"
    if valid > 0:
        return "VALID_OPEN_PAPER_TRADE"
    return "OK"


def _plan_decision(audit: Mapping[str, Any]) -> str:
    if audit.get("config_error_blocking"):
        return "FIX_CONFIG_AND_RERUN"
    if audit.get("requires_paper_only_close"):
        return "CLOSE_STALE_OPEN_PAPER_TRADE_PAPER_ONLY"
    if int(audit.get("invalid_risk_open_trade_count", 0) or 0) > 0:
        return "MANUAL_REVIEW_REQUIRED"
    if audit.get("can_safely_continue_with_open_trade"):
        return "RESUME_WITH_VALID_OPEN_PAPER_TRADE"
    if int(audit.get("open_paper_trades_count", 0) or 0) > 0:
        return "WAIT_FOR_TRADE_EXIT"
    return "MANUAL_REVIEW_REQUIRED" if audit.get("recovery_required") else "FIX_CONFIG_AND_RERUN"


def _plan_markdown(audit: Mapping[str, Any], decision: str) -> str:
    return f"""# Paper State Recovery Plan

Decision: `{decision}`

- config_error_root_cause: `{audit.get('config_error_root_cause', '')}`
- open_paper_trades_count: `{audit.get('open_paper_trades_count', 0)}`
- stale_open_trade_count: `{audit.get('stale_open_trade_count', 0)}`
- orphan_open_trade_count: `{audit.get('orphan_open_trade_count', 0)}`
- invalid_risk_open_trade_count: `{audit.get('invalid_risk_open_trade_count', 0)}`
- execution_attempted=false
- order_send_called=false
- order_check_called=false

This plan is paper/shadow only and never touches MT5 positions.
"""


def _plan_commands(decision: str) -> str:
    lines = ['$ErrorActionPreference = "Stop"', 'Set-Location (Split-Path -Parent $PSScriptRoot)', '$env:PYTHONPATH = "src/python"', ""]
    if decision == "CLOSE_STALE_OPEN_PAPER_TRADE_PAPER_ONLY":
        lines.append('py -m agi_style_forex_bot_mt5.cli --mode paper-close-stale-open-trade --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --output-dir data\\reports\\paper_state_recovery --confirm-paper-only true --reason "paper-only stale open trade recovery"')
    elif decision == "FIX_CONFIG_AND_RERUN":
        lines.append('py -m agi_style_forex_bot_mt5.cli --mode paper-state-recovery-audit --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root data\\reports --output-dir data\\reports\\paper_state_recovery')
    else:
        lines.append('py -m agi_style_forex_bot_mt5.cli --mode forward-acceptance --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --reports-root data\\reports --output-dir data\\reports\\forward_evidence')
    return "\n".join(lines) + "\n"


def _config_fix(root: str) -> str:
    fixes = {
        "missing_profile_config": "Provide --profile-config data\\reports\\paper_risk\\balanced_stable_micro.ini.",
        "missing_stable_gate": "Provide --stable-gate data\\reports\\stable_gate\\stable_gate_summary.json.",
        "missing_paper_risk_clearance": "Provide --paper-risk-clearance or --clearance-ledger pointing to paper_risk_clearance_ledger.json.",
        "missing_daily_risk_ledger": "Provide --daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json.",
        "config_parse_error": "Repair the profile INI syntax.",
        "profile_mismatch": "Use a BALANCED_STABLE_MICRO profile config.",
        "stable_gate_not_accepted": "Rerun stable gate; paper_shadow_ready must be true.",
        "unknown_config_error": "Review latest_forward_shadow_error in operational state and forward-shadow logs.",
        "MISSING_PROFILE_CONFIG": "Provide --profile-config data\\reports\\paper_risk\\balanced_stable_micro.ini.",
        "MISSING_STABLE_GATE": "Provide --stable-gate data\\reports\\stable_gate\\stable_gate_summary.json.",
        "MISSING_CLEARANCE_LEDGER": "Provide --paper-risk-clearance or --clearance-ledger pointing to paper_risk_clearance_ledger.json.",
        "MISSING_DAILY_RISK_LEDGER": "Provide --daily-risk-ledger data\\reports\\paper_daily_risk\\paper_daily_risk_ledger.json.",
        "INVALID_PROFILE_CONFIG_SCHEMA": "Repair or rebuild balanced_stable_micro.ini.",
        "INVALID_STABLE_GATE_SCHEMA": "Rerun stable-robustness-gate and verify the gate schema.",
        "INVALID_CLEARANCE_LEDGER_SCHEMA": "Regenerate the paper risk clearance ledger.",
        "INVALID_DAILY_RISK_LEDGER_SCHEMA": "Regenerate the daily paper risk ledger.",
        "PROFILE_MISMATCH": "Use BALANCED_STABLE_MICRO with the matching profile config.",
        "STABLE_GATE_NOT_ACCEPTED": "Rerun stable gate; paper_shadow_ready must be true.",
        "PAPER_RISK_NOT_ACCEPTED": "Regenerate paper-risk-clearance for BALANCED_STABLE_MICRO.",
        "DAILY_RISK_LEDGER_NOT_ACCEPTED": "Regenerate paper-daily-risk-clear for BALANCED_STABLE_MICRO.",
        "MISSING_REQUIRED_FORWARD_SHADOW_ARG": "Rerun forward-shadow with all required micro paper/shadow arguments.",
        "INVALID_SYMBOLS_ARG": "Use a valid comma-separated --symbols list.",
        "INVALID_SIGNAL_PROFILE": "Use --signal-profile BALANCED_STABLE_MICRO.",
        "CONFIG_PARSE_EXCEPTION": "Repair the config parser exception reported by config-error-root-cause-audit.",
        "RUNTIME_CONFIG_PATH_ERROR": "Fix the invalid runtime config path.",
        "FORWARD_SHADOW_CONFIG_EXCEPTION": "Inspect the forward-shadow exception and repair the paper state/config source before rerun.",
        "UNKNOWN_CONFIG_ERROR": "Review latest_forward_shadow_error in operational state and forward-shadow logs.",
    }
    return fixes.get(root, "No config repair required.")


def _merge_root_cause_audit(config: Mapping[str, Any], audit_path: Path) -> dict[str, Any]:
    merged = dict(config)
    if not merged.get("config_error_detected"):
        merged["config_error_resolved"] = True
        merged["can_rerun_forward_shadow_after_fix"] = True
        return merged
    if merged.get("config_error_root_cause") and merged.get("config_error_root_cause") != "unknown_config_error":
        return merged
    audit = _load_json(audit_path)
    root = str(audit.get("config_error_root_cause") or audit.get("primary_root_cause") or "")
    if root and root != "UNKNOWN_CONFIG_ERROR":
        merged["config_error_root_cause"] = root
        merged["recommended_config_fix"] = str(audit.get("recommended_fix") or _config_fix(root))
        merged["can_rerun_forward_shadow_after_fix"] = bool(audit.get("can_rerun_forward_shadow_after_fix", False))
        merged["config_error_evidence"] = str(audit.get("config_error_evidence", ""))
        merged["source_file_or_log"] = str(audit.get("source_file_or_log", ""))
        merged["unknown_config_error"] = False
    return merged


def _parse_profile_config(path: Path) -> dict[str, Any]:
    parser = configparser.ConfigParser(strict=False)
    try:
        text = path.read_text(encoding="utf-8")
        parser.read_string(text if text.lstrip().startswith("[") else "[profile]\n" + text)
        section = parser["profile"] if parser.has_section("profile") else parser.defaults()
        return {key: value for key, value in section.items()}
    except Exception as exc:
        return {"config_parse_error": str(exc)}


def _missing(path: str | Path | None) -> bool:
    return path is None or not Path(path).exists()


def _invalid_risk_distance(trade: Mapping[str, Any]) -> bool:
    try:
        entry = float(trade.get("entry_price"))
        stop_loss = float(trade.get("sl_price"))
    except Exception:
        return False
    return abs(entry - stop_loss) <= 0


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _audit(database: TelemetryDatabase, event_type: str, severity: Severity, payload: Mapping[str, Any]) -> None:
    event = Event.create(
        run_id="paper_state_recovery",
        environment=Environment.DEMO,
        severity=severity,
        module="paper_state_recovery",
        event_type=event_type,
        message=event_type.lower(),
        correlation_id=f"paper_state_recovery:{event_type}",
        payload={**dict(payload), "execution_attempted": False, "order_send_called": False, "order_check_called": False},
    )
    database.insert_event(event)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
