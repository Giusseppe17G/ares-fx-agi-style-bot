"""Heartbeat freshness checks for Micro V2 dry-run monitoring."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from agi_style_forex_bot_mt5.forward_sufficiency.observation_window import calculate_observation_window
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


def audit_heartbeat(dataset: Mapping[str, Any], *, now_utc: datetime | None = None, stale_after_minutes: int = 15) -> dict[str, Any]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    heartbeats = list(dataset.get("heartbeats", []))
    heartbeat_events = [event for event in dataset.get("events", []) if str(event.get("event_type", "")).upper() == "HEARTBEAT"]
    all_heartbeats = [*heartbeats, *heartbeat_events]
    latest_dt = _latest_timestamp(all_heartbeats)
    age_seconds = None
    if latest_dt is not None:
        age_seconds = max((now - latest_dt).total_seconds(), 0.0)
    recent = age_seconds is not None and age_seconds <= stale_after_minutes * 60
    window = calculate_observation_window([*dataset.get("events", []), *heartbeats, *dataset.get("paper_trades", [])])
    return {
        "heartbeat_count": len(all_heartbeats),
        "latest_heartbeat_utc": latest_dt.isoformat() if latest_dt else None,
        "heartbeat_age_seconds": None if age_seconds is None else round(age_seconds, 2),
        "heartbeat_recent": recent,
        "heartbeat_stale": bool(all_heartbeats) and not recent,
        "process_appears_active": recent,
        "stale_after_minutes": stale_after_minutes,
        **window,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _latest_timestamp(rows: list[Mapping[str, Any]]) -> datetime | None:
    values: list[datetime] = []
    for row in rows:
        parsed = safe_parse_datetime(row.get("timestamp_utc"), field_name="timestamp_utc", source=str(row.get("source", "micro_v2_dry_run_monitor")))
        if parsed.value is not None:
            values.append(parsed.value.astimezone(timezone.utc))
    return max(values) if values else None
