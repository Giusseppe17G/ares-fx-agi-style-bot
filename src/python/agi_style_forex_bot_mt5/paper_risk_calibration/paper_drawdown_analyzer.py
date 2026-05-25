"""Analyze paper-forward drawdown and halt history."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def analyze_paper_drawdown(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
) -> dict[str, Any]:
    """Compute paper risk history without altering SQLite or logs."""

    trades = [_payload(row) for row in database.fetch_paper_trades()]
    metrics = _paper_metrics(trades)
    alerts = [_payload(row) for row in database.fetch_all("alerts")]
    log_events = _load_log_events(Path(log_dir))
    paper_state = _load_json(Path(reports_root) / "paper_state" / "paper_state_report.json")
    evidence = _load_json(Path(reports_root) / "forward_evidence" / "evidence_summary.json")
    drawdown_events = [
        event
        for event in [*alerts, *log_events]
        if str(event.get("alert_code") or event.get("event_type") or event.get("halt_reason") or "").upper() in {"PAPER_DAILY_DRAWDOWN", "PAPER_SHADOW_HALTED", "PAPER_DAILY_DRAWDOWN_HALT"}
    ]
    closed = [trade for trade in trades if str(trade.get("status", "")).upper() == "CLOSED"]
    open_trades = [trade for trade in trades if str(trade.get("status", "")).upper() == "OPEN"]
    losses = [trade for trade in closed if float(trade.get("profit") or 0.0) < 0]
    by_symbol: defaultdict[str, float] = defaultdict(float)
    by_strategy: defaultdict[str, float] = defaultdict(float)
    for trade in losses:
        by_symbol[str(trade.get("symbol") or "UNKNOWN").upper()] += float(trade.get("profit") or 0.0)
        by_strategy[str(trade.get("strategy_name") or "UNKNOWN")] += float(trade.get("profit") or 0.0)
    worst_pnl = min((float(trade.get("profit") or 0.0) for trade in closed), default=0.0)
    average_pnl = sum(float(trade.get("profit") or 0.0) for trade in closed) / len(closed) if closed else 0.0
    daily_limit = float(paper_state.get("daily_drawdown_limit", -3.0) or -3.0)
    one_trade_can_breach = bool(drawdown_events and worst_pnl <= daily_limit)
    classification = _classification(trades, drawdown_events, one_trade_can_breach)
    return {
        "mode": "paper-risk-audit",
        "classification": classification,
        "paper_risk_status": classification,
        "paper_trades_total": len(trades),
        "paper_trades_closed": len(closed),
        "paper_trades_open": len(open_trades),
        "max_paper_drawdown": metrics.get("max_drawdown_shadow", 0.0),
        "daily_drawdown_events": len(drawdown_events),
        "symbols_causing_drawdown": _counter_rows(by_symbol),
        "strategies_causing_drawdown": _counter_rows(by_strategy),
        "average_paper_pnl": average_pnl,
        "worst_paper_pnl": worst_pnl,
        "risk_per_trade_approximation": max((abs(float(trade.get("r_multiple") or 0.0)) for trade in closed), default=0.0),
        "one_trade_can_breach_daily_drawdown": one_trade_can_breach,
        "paper_daily_halt_frequency": len(drawdown_events),
        "recommended_safer_profile": "BALANCED_STABLE_MICRO" if classification != "PAPER_RISK_OK" else "",
        "paper_state_status": paper_state.get("halt_reason", ""),
        "forward_evidence_status": evidence.get("operational_acceptance", ""),
        "drawdown_events": drawdown_events,
        "trade_rows": trades,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _classification(trades: list[Mapping[str, Any]], drawdown_events: list[Mapping[str, Any]], one_trade_can_breach: bool) -> str:
    if not trades and not drawdown_events:
        return "PAPER_RISK_UNKNOWN_REVIEW"
    if drawdown_events and one_trade_can_breach:
        return "PAPER_PROFILE_NEEDS_MICRO_RISK"
    if drawdown_events:
        return "PAPER_RISK_TOO_HIGH"
    return "PAPER_RISK_OK"


def _paper_metrics(trades: list[Mapping[str, Any]]) -> dict[str, float]:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        if str(trade.get("status", "")).upper() != "CLOSED":
            continue
        equity += float(trade.get("profit") or 0.0)
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return {"max_drawdown_shadow": max_drawdown}


def _counter_rows(values: Mapping[str, float]) -> list[dict[str, Any]]:
    return [{"name": key, "paper_pnl": value} for key, value in sorted(values.items(), key=lambda item: item[1])]


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        try:
            return dict(row)
        except Exception:
            return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_log_events(log_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not log_dir.exists():
        return rows
    for path in log_dir.glob("*.jsonl"):
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            continue
    return rows
