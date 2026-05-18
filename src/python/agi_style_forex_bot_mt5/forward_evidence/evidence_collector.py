"""Collect BALANCED_STABLE forward-shadow evidence from local artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def collect_forward_evidence(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
) -> dict[str, Any]:
    """Return an operational evidence summary from SQLite, JSONL and reports."""

    events = [_row_payload(row) for row in database.fetch_all("events")]
    heartbeats = [_row_payload(row) for row in database.fetch_all("heartbeats")]
    trades = [_row_payload(row) for row in database.fetch_paper_trades()]
    jsonl_events = _read_jsonl_events(Path(log_dir))
    all_events = [*events, *jsonl_events]
    timestamps = [parsed for parsed in (_parse_time(item.get("timestamp_utc")) for item in [*heartbeats, *all_events] if item.get("timestamp_utc")) if parsed is not None]
    start = min(timestamps) if timestamps else None
    end = max(timestamps) if timestamps else None
    stable_gate = _load_json(Path(reports_root) / "stable_gate" / "stable_gate_summary.json")
    symbols_seen = sorted({str(item.get("symbol")) for item in all_events if item.get("symbol")})
    execution_attempted = any(bool(_payload_dict(item).get("execution_attempted", False)) for item in all_events)
    event_types = [str(item.get("event_type", "")) for item in all_events]
    paper_opened = sum(1 for item in event_types if item == "PAPER_TRADE_OPENED")
    paper_closed = sum(1 for item in event_types if item == "PAPER_TRADE_CLOSED")
    return {
        "mode": "forward-evidence",
        "observation_start": start.isoformat() if start else None,
        "observation_end": end.isoformat() if end else None,
        "hours_observed": _hours(start, end),
        "cycles_completed": sum(1 for item in event_types if item == "FORWARD_SHADOW_CYCLE"),
        "heartbeat_count": len(heartbeats),
        "mt5_connected_count": sum(1 for item in heartbeats if bool(item.get("mt5_connected", False))),
        "symbols_seen": symbols_seen,
        "signals_detected": sum(1 for item in event_types if item == "SIGNAL_DETECTED"),
        "signals_rejected": sum(1 for item in event_types if item == "SIGNAL_REJECTED"),
        "paper_trades_opened": paper_opened or sum(1 for trade in trades if trade),
        "paper_trades_closed": paper_closed or sum(1 for trade in trades if str(trade.get("status", "")).upper() == "CLOSED"),
        "open_paper_trades": sum(1 for trade in trades if str(trade.get("status", "")).upper() == "OPEN"),
        "stable_gate_confirmed": stable_gate.get("stable_gate_decision") == "PAPER_SHADOW_READY",
        "paper_shadow_ready": stable_gate.get("paper_shadow_ready") is True,
        "execution_attempted": bool(execution_attempted),
        "order_send_called": any("order_send" in json.dumps(item).lower() and "not called" not in json.dumps(item).lower() for item in all_events),
        "order_check_called": any("order_check" in json.dumps(item).lower() and "not called" not in json.dumps(item).lower() for item in all_events),
    }


def _row_payload(row: Any) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
        if "event_type" not in payload and "event_type" in row.keys():
            payload["event_type"] = row["event_type"]
        if "timestamp_utc" not in payload and "timestamp_utc" in row.keys():
            payload["timestamp_utc"] = row["timestamp_utc"]
        if "symbol" not in payload and "symbol" in row.keys():
            payload["symbol"] = row["symbol"]
        return payload
    except Exception:
        return {}


def _payload_dict(item: Mapping[str, Any]) -> dict[str, Any]:
    payload = item.get("payload")
    if isinstance(payload, Mapping):
        return dict(payload)
    payload_json = item.get("payload_json")
    if payload_json:
        try:
            return json.loads(str(payload_json))
        except json.JSONDecodeError:
            return {}
    return dict(item)


def _read_jsonl_events(log_dir: Path) -> list[dict[str, Any]]:
    if not log_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _hours(start: datetime | None, end: datetime | None) -> float:
    if start is None or end is None:
        return 0.0
    return max(0.0, (end - start).total_seconds() / 3600.0)
