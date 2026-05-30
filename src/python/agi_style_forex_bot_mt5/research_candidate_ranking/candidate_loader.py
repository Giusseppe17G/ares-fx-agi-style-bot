"""Read-only loaders for offline research candidate ranking."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


REJECTION_EVENTS = {"SIGNAL_REJECTED", "STRATEGY_BLOCKED_BY_CONTEXT", "RISK_REJECTED", "SYMBOL_REJECTED", "STALE_TICK_REJECTION", "MARKET_CLOSED_REJECTION", "FUTURE_SIGNAL_REJECTION", "INVALID_MARKET_SNAPSHOT_REJECTION", "FORWARD_CANDIDATE_BLOCKED", "FORWARD_NO_SIGNAL_DIAGNOSTIC"}
SIGNAL_EVENTS = {"SIGNAL_ACCEPTED", "PAPER_TRADE_OPENED", "FORWARD_CANDIDATE_EVALUATED", "FORWARD_NEAR_MISS"}


def load_research_inputs(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
) -> dict[str, Any]:
    """Load reports, SQLite events and paper trades without mutation."""

    reports = Path(reports_root)
    events = [_event_row(row) for row in database.fetch_all("events")]
    paper_trades = [_payload(row) for row in database.fetch_paper_trades()]
    return {
        "reports_root": str(reports),
        "log_dir": str(log_dir),
        "forward_evidence": _load_json(reports / "forward_evidence" / "evidence_summary.json"),
        "forward_metrics": _load_json(reports / "forward_evidence" / "forward_metrics.json"),
        "drift_summary": _load_json(reports / "forward_evidence" / "drift_summary.json"),
        "paper_trade_audit": _load_json(reports / "forward_evidence" / "paper_trade_audit.json"),
        "paper_pnl_audit": _load_json(reports / "paper_pnl_audit" / "paper_pnl_audit_summary.json"),
        "paper_risk_status": _load_json(reports / "paper_risk" / "paper_risk_status.json"),
        "status_summary": _load_json(reports / "operator_dashboard" / "operator_dashboard_summary.json"),
        "rejections_csv": _load_csv(reports / "forward_evidence" / "rejections.csv"),
        "events": events,
        "paper_trades": paper_trades,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def build_candidate_events(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return normalized event rows for candidate ranking."""

    rows: list[dict[str, Any]] = []
    for event in inputs.get("events", []):
        event_type = str(event.get("event_type", ""))
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        if event_type not in REJECTION_EVENTS | SIGNAL_EVENTS:
            continue
        reason = _reason(event, payload)
        symbol = str(event.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "UNKNOWN")
        strategy = str(payload.get("strategy_name") or payload.get("strategy") or payload.get("strategy_id") or "UNKNOWN")
        rows.append(
            {
                "event_type": event_type,
                "symbol": symbol or "UNKNOWN",
                "strategy_name": strategy or "UNKNOWN",
                "reason": reason,
                "session": str(payload.get("session") or ""),
                "regime": str(payload.get("regime") or ""),
                "spread_points": _float(payload.get("spread_points"), 0.0),
                "setup_score": _float(payload.get("setup_score"), 0.0),
                "ensemble_score": _float(payload.get("ensemble_score") or payload.get("signal_score"), 0.0),
                "is_rejection": event_type in REJECTION_EVENTS,
                "is_signal": event_type in SIGNAL_EVENTS or event_type in REJECTION_EVENTS,
                "execution_attempted": False,
            }
        )
    for trade in inputs.get("paper_trades", []):
        rows.append(
            {
                "event_type": "PAPER_TRADE",
                "symbol": str(trade.get("symbol") or "UNKNOWN"),
                "strategy_name": str(trade.get("strategy_name") or "UNKNOWN"),
                "reason": "",
                "session": str(trade.get("session") or ""),
                "regime": str(trade.get("regime") or ""),
                "spread_points": _float(trade.get("spread_points"), 0.0),
                "setup_score": _float(trade.get("setup_score") or trade.get("score"), 0.0),
                "ensemble_score": _float(trade.get("ensemble_score") or trade.get("score"), 0.0),
                "is_rejection": False,
                "is_signal": True,
                "execution_attempted": False,
            }
        )
    return rows


def _event_row(row: Any) -> dict[str, Any]:
    try:
        payload = _loads(row["payload_json"])
        return {
            "event_type": row["event_type"],
            "symbol": row["symbol"],
            "timestamp_utc": row["timestamp_utc"],
            "severity": row["severity"],
            "payload": payload,
        }
    except Exception:
        return {}


def _reason(event: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    reasons = payload.get("blocking_reasons")
    if isinstance(reasons, list) and reasons:
        return str(reasons[0])
    return str(payload.get("reject_reason") or payload.get("reject_code") or payload.get("reason") or event.get("event_type") or "")


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _load_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default
