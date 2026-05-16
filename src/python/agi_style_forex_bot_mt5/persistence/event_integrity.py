"""Audit integrity checks for replay and operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def validate_event_integrity(
    *,
    database: TelemetryDatabase | None = None,
    events: Iterable[Mapping[str, Any]] | None = None,
    heartbeat_gap_seconds: int = 180,
) -> dict[str, Any]:
    """Detect duplicate, missing, and inconsistent audit records."""

    issues: list[dict[str, Any]] = []
    event_rows = list(events or _events_from_db(database))
    keys: dict[str, int] = {}
    previous_time: datetime | None = None
    for row in event_rows:
        key = str(row.get("idempotency_key") or "")
        if key:
            keys[key] = keys.get(key, 0) + 1
        timestamp = str(row.get("timestamp_utc") or "")
        try:
            current = datetime.fromisoformat(timestamp)
            if previous_time is not None and current < previous_time:
                issues.append({"code": "EVENT_OUT_OF_ORDER", "timestamp_utc": timestamp})
            previous_time = current
        except ValueError:
            issues.append({"code": "EVENT_TIMESTAMP_INVALID", "timestamp_utc": timestamp})
    for key, count in keys.items():
        if count > 1:
            issues.append({"code": "DUPLICATE_IDEMPOTENCY_KEY", "idempotency_key": key, "count": count})
    if database is not None:
        issues.extend(_heartbeat_gaps(database, heartbeat_gap_seconds))
        issues.extend(_paper_trade_consistency(database))
        issues.extend(_associated_signal_checks(database))
        telegram_errors = sum(1 for row in database.fetch_all("events") if row["event_type"] == "TELEGRAM_ERROR")
        if telegram_errors >= 3:
            issues.append({"code": "TELEGRAM_ERROR_RECURRENT", "count": telegram_errors})
    return {
        "mode": "event-integrity",
        "status": "OK" if not issues else "WARNING",
        "event_gap_count": sum(1 for issue in issues if issue["code"] == "HEARTBEAT_GAP"),
        "issues": issues,
        "replay_possible": True,
        "execution_attempted": False,
    }


def _events_from_db(database: TelemetryDatabase | None) -> list[dict[str, Any]]:
    if database is None:
        return []
    return [dict(row) for row in database.fetch_all("events")]


def _heartbeat_gaps(database: TelemetryDatabase, gap_seconds: int) -> list[dict[str, Any]]:
    rows = database.fetch_all("heartbeats")
    issues: list[dict[str, Any]] = []
    previous: datetime | None = None
    for row in rows:
        current = datetime.fromisoformat(str(row["timestamp_utc"]))
        if previous is not None and (current - previous).total_seconds() > gap_seconds:
            issues.append({"code": "HEARTBEAT_GAP", "gap_seconds": (current - previous).total_seconds()})
        previous = current
    return issues


def _paper_trade_consistency(database: TelemetryDatabase) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    opened = set()
    closed = set()
    for row in database.fetch_all("paper_trade_events"):
        if row["event_type"] == "PAPER_TRADE_OPENED":
            opened.add(row["paper_trade_id"])
        if row["event_type"] == "PAPER_TRADE_CLOSED":
            closed.add(row["paper_trade_id"])
    for trade_id in closed - opened:
        issues.append({"code": "PAPER_TRADE_CLOSED_WITHOUT_OPENED", "paper_trade_id": trade_id})
    return issues


def _associated_signal_checks(database: TelemetryDatabase) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    signal_events = {row["signal_id"] for row in database.fetch_all("events") if row["event_type"] == "SIGNAL_DETECTED" and row["signal_id"]}
    for row in database.fetch_all("events"):
        if row["event_type"] in {"ML_PREDICTION", "PORTFOLIO_DECISION"}:
            signal_id = row["signal_id"]
            if signal_id and signal_id not in signal_events:
                issues.append({"code": f"{row['event_type']}_WITHOUT_SIGNAL", "signal_id": signal_id})
        if row["event_type"] == "SHADOW_ORDER_CREATED":
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                payload = {}
            if not payload.get("risk_decision", {}).get("accepted", False):
                issues.append({"code": "SHADOW_ORDER_WITHOUT_ACCEPTED_RISK", "signal_id": row["signal_id"]})
    return issues

