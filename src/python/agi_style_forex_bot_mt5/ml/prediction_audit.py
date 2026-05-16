"""Persist ML prediction audit records."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def audit_ml_prediction(database: TelemetryDatabase, payload: Mapping[str, Any]) -> bool:
    data = {**dict(payload), "execution_attempted": False}
    return database.insert_record(
        "model_predictions",
        data,
        idempotency_key=str(data.get("idempotency_key") or f"ml_prediction:{data.get('signal_id', '')}:{data.get('timestamp_utc', '')}"),
    )

