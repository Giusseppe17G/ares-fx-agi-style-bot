"""Persistent heartbeat writer."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from agi_style_forex_bot_mt5.contracts import utc_now
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


class HeartbeatWriter:
    """Write forward-shadow heartbeats to SQLite."""

    def __init__(self, database: TelemetryDatabase) -> None:
        self.database = database

    def write(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        heartbeat = {
            "heartbeat_id": f"hb_{uuid4().hex}",
            "timestamp_utc": utc_now().isoformat(),
            "mode": "forward-shadow",
            "mt5_connected": False,
            "symbols_seen": 0,
            "symbols_rejected": 0,
            "open_paper_trades": 0,
            "closed_paper_trades_today": 0,
            "last_error": "",
            "execution_attempted": False,
            **dict(payload),
        }
        heartbeat["execution_attempted"] = False
        self.database.insert_heartbeat(heartbeat)
        self.database.update_operational_state({"last_heartbeat_utc": heartbeat["timestamp_utc"]})
        return heartbeat

