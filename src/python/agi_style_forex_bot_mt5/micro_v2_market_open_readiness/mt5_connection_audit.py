"""MT5 connection status from V2 heartbeat telemetry."""

from __future__ import annotations

from typing import Any, Mapping


def audit_mt5_connection(dataset: Mapping[str, Any]) -> dict[str, Any]:
    heartbeats = list(dataset.get("heartbeats", []))
    latest = heartbeats[-1] if heartbeats else {}
    payload = latest.get("payload", {}) if isinstance(latest.get("payload"), Mapping) else {}
    mt5_connected = bool(latest.get("mt5_connected", payload.get("mt5_connected", False)))
    return {
        "mt5_connected": mt5_connected,
        "latest_heartbeat_utc": latest.get("timestamp_utc"),
        "heartbeat_count": len(heartbeats),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
