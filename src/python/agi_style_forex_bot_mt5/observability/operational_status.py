"""CLI status and health helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.observability.metrics_collector import MetricsCollector
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def build_status(database: TelemetryDatabase) -> dict[str, Any]:
    metrics = MetricsCollector(database).collect()
    state = database.get_operational_state()
    latest = database.get_latest_health()
    return {
        "mode": "status",
        "shadow_paused": bool(state.get("shadow_paused", False)),
        "last_heartbeat_utc": latest.get("last_heartbeat_utc"),
        "metrics": metrics,
        "execution_attempted": False,
    }


def build_health_status(database: TelemetryDatabase, *, log_dir: str | Path | None = None) -> dict[str, Any]:
    latest = database.get_latest_health()
    log_status = "UNKNOWN"
    if log_dir is not None:
        log_status = "OK" if any(Path(log_dir).rglob("*.jsonl")) else "WARNING"
    return {
        "mode": "health",
        "status": "OK" if latest.get("last_heartbeat_utc") else "WARNING",
        "latest_health": latest,
        "sqlite_status": "OK",
        "jsonl_status": log_status,
        "execution_attempted": False,
    }

