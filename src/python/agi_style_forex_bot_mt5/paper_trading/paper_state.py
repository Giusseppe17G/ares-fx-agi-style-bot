"""Safe paper/shadow state inspection and paper-only lifecycle commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from agi_style_forex_bot_mt5.contracts import Environment, Event, Severity
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime

from .paper_performance import paper_metrics
from .paper_pnl_engine import pnl_value


def build_paper_open_trades_report(*, database: TelemetryDatabase, output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows = [_payload(row) for row in database.fetch_open_paper_trades()]
    report_rows = [_open_trade_row(row) for row in rows]
    paths = [output / "paper_open_trades.json", output / "paper_open_trades.csv"]
    paths[0].write_text(json.dumps(_jsonable({"mode": "paper-open-trades", "open_paper_trades": len(report_rows), "trades": report_rows, "execution_attempted": False}), indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame(report_rows).to_csv(paths[1], index=False)
    return {
        "mode": "paper-open-trades",
        "open_paper_trades": len(report_rows),
        "trades": report_rows,
        "reports_created": [str(path) for path in paths],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def build_paper_state_report(*, database: TelemetryDatabase, log_dir: str | Path | None = None, output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trades = [_payload(row) for row in database.fetch_paper_trades()]
    metrics = paper_metrics(trades)
    state = database.get_operational_state()
    halt_reason = _halt_reason(metrics, state)
    summary = {
        "mode": "paper-state-report",
        "paper_trades_open": int(metrics.get("open_trades", 0) or 0),
        "paper_trades_closed_today": _closed_today(trades),
        "paper_drawdown": metrics.get("daily_drawdown_shadow", 0.0),
        "raw_drawdown": metrics.get("raw_drawdown_shadow", metrics.get("daily_drawdown_shadow", 0.0)),
        "scaled_drawdown": metrics.get("scaled_drawdown_shadow", metrics.get("daily_drawdown_shadow", 0.0)),
        "drawdown_basis": metrics.get("drawdown_basis", "SCALED_PAPER_PNL"),
        "legacy_unscaled_trade_count": metrics.get("legacy_unscaled_trade_count", 0),
        "scaled_trade_count": metrics.get("scaled_trade_count", 0),
        "daily_drawdown_limit": -3.0,
        "paper_shadow_paused": bool(state.get("shadow_paused", False)),
        "halt_reason": halt_reason,
        "recommended_action": _recommended_action(halt_reason),
        "duration_parse_status": metrics.get("duration_parse_status"),
        "invalid_timestamp_count": metrics.get("invalid_timestamp_count", 0),
        "invalid_timestamp_examples": metrics.get("invalid_timestamp_examples", []),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = output / "paper_state_report.json"
    path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path)]
    return summary


def close_all_paper_trades(*, database: TelemetryDatabase, reason: str, output_dir: str | Path, confirm_paper_only: bool = False) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    open_rows = [_payload(row) for row in database.fetch_open_paper_trades()]
    now = datetime.now(timezone.utc).isoformat()
    closed_payloads: list[dict[str, Any]] = []
    if confirm_paper_only:
        for trade in open_rows:
            closed = {
                **trade,
                "status": "CLOSED",
                "exit_time_utc": now,
                "exit_price": trade.get("exit_price") or trade.get("entry_price"),
                "exit_reason": "MANUAL_PAPER_CLOSE",
                "profit": float(trade.get("profit") or 0.0),
                "r_multiple": float(trade.get("r_multiple") or 0.0),
                "metadata": {**(trade.get("metadata") if isinstance(trade.get("metadata"), dict) else {}), "manual_close_reason": reason, "fill_quality": "MANUAL_PAPER_CLOSE_LAST_KNOWN"},
            }
            database.update_paper_trade(closed)
            database.insert_paper_trade_event(str(closed.get("paper_trade_id")), "PAPER_TRADE_MANUAL_CLOSE", closed)
            _audit(database, "PAPER_TRADE_MANUAL_CLOSE", Severity.WARNING, closed)
            closed_payloads.append(closed)
    summary = {
        "mode": "paper-close-all",
        "dry_run": not confirm_paper_only,
        "confirm_paper_only": bool(confirm_paper_only),
        "paper_trades_found": len(open_rows),
        "paper_trades_closed": len(closed_payloads),
        "reason": reason,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = output / "paper_close_all_report.json"
    path.write_text(json.dumps(_jsonable({**summary, "closed_trades": closed_payloads}), indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"] = [str(path)]
    return summary


def pause_shadow(*, database: TelemetryDatabase, reason: str) -> dict[str, Any]:
    state = database.set_shadow_paused(True, reason=reason, paused_by="cli")
    _audit(database, "SHADOW_MANUALLY_PAUSED", Severity.WARNING, {"reason": reason, "state": state, "execution_attempted": False})
    return {"mode": "pause-shadow", "paper_shadow_paused": True, "reason": reason, "state": state, "execution_attempted": False, "order_send_called": False, "order_check_called": False}


def resume_shadow(*, database: TelemetryDatabase, reason: str) -> dict[str, Any]:
    state = database.set_shadow_paused(False, reason=reason, paused_by="cli")
    _audit(database, "SHADOW_MANUALLY_RESUMED", Severity.INFO, {"reason": reason, "state": state, "execution_attempted": False})
    return {"mode": "resume-shadow", "paper_shadow_paused": False, "reason": reason, "state": state, "execution_attempted": False, "order_send_called": False, "order_check_called": False}


def _open_trade_row(trade: Mapping[str, Any]) -> dict[str, Any]:
    opened = safe_parse_datetime(trade.get("entry_time_utc"), field_name="entry_time_utc", source="paper-open-trades")
    age = None
    if opened.value is not None:
        age = (datetime.now(timezone.utc) - opened.value).total_seconds()
    return {
        "trade_id": trade.get("paper_trade_id"),
        "symbol": trade.get("symbol"),
        "strategy_name": trade.get("strategy_name"),
        "opened_at": trade.get("entry_time_utc"),
        "entry_price": trade.get("entry_price"),
        "current_price": trade.get("exit_price") or trade.get("entry_price"),
        "unrealized_pnl": pnl_value(trade),
        "raw_pnl": trade.get("raw_pnl", trade.get("profit", 0.0)),
        "scaled_paper_pnl": pnl_value(trade),
        "pnl_scaling_status": trade.get("pnl_scaling_status", "LEGACY_UNSCALED_PNL"),
        "age_seconds": age,
        "stop_loss": trade.get("sl_price"),
        "take_profit": trade.get("tp_price"),
        "timestamp_parse_status": opened.status,
        "timestamp_warning": opened.warning,
        "execution_attempted": False,
    }


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def _closed_today(trades: list[Mapping[str, Any]]) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for trade in trades if str(trade.get("status", "")).upper() == "CLOSED" and str(trade.get("exit_time_utc", ""))[:10] == today)


def _halt_reason(metrics: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    if bool(state.get("shadow_paused", False)):
        return "SHADOW_MANUALLY_PAUSED"
    if float(metrics.get("daily_drawdown_shadow", 0.0) or 0.0) <= -3.0:
        return "PAPER_DAILY_DRAWDOWN_HALT"
    if int(metrics.get("open_trades", 0) or 0) > 0:
        return "OPEN_TRADES_REVIEW_REQUIRED"
    return ""


def _recommended_action(halt_reason: str) -> str:
    if halt_reason == "PAPER_DAILY_DRAWDOWN_HALT":
        return "Pause shadow, inspect paper-open-trades, then decide whether to paper-close-all."
    if halt_reason == "SHADOW_MANUALLY_PAUSED":
        return "Review paper state before resume-shadow."
    if halt_reason == "OPEN_TRADES_REVIEW_REQUIRED":
        return "Inspect open paper trades before starting another observation window."
    return "Continue monitoring."


def _audit(database: TelemetryDatabase, event_type: str, severity: Severity, payload: Mapping[str, Any]) -> None:
    event = Event.create(
        run_id="paper_state",
        environment=Environment.DEMO,
        severity=severity,
        module="paper_state",
        event_type=event_type,
        message=event_type.lower(),
        correlation_id=f"paper_state:{event_type}",
        payload={**dict(payload), "execution_attempted": False},
    )
    database.insert_event(event)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
