"""Incident logging adapter."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from agi_style_forex_bot_mt5.contracts import utc_now
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def log_incident(database: TelemetryDatabase, payload: Mapping[str, Any]) -> dict[str, Any]:
    incident = {
        "incident_id": f"inc_{uuid4().hex}",
        "timestamp_utc": utc_now().isoformat(),
        "severity": "WARNING",
        "incident_code": "INCIDENT",
        "execution_attempted": False,
        **dict(payload),
    }
    database.insert_incident(incident)
    database.update_operational_state({"last_incident_utc": incident["timestamp_utc"]})
    return incident

