"""Utilities for writing forward candidate diagnostics to telemetry."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.contracts import Environment, Event, Severity
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def audit_forward_candidate(
    *,
    database: TelemetryDatabase,
    audit_logger: JsonlAuditLogger | None,
    run_id: str,
    event_type: str,
    payload: Mapping[str, Any],
    symbol: str | None = None,
) -> None:
    """Persist a diagnostic candidate event without creating paper trades."""

    event = Event.create(
        run_id=run_id,
        environment=Environment.DEMO,
        severity=Severity.INFO if event_type != "FORWARD_CANDIDATE_BLOCKED" else Severity.WARNING,
        module="forward_diagnostics",
        event_type=event_type,
        message=event_type.lower(),
        correlation_id=f"{run_id}:{event_type}:{symbol or ''}",
        symbol=symbol,
        payload={**dict(payload), "execution_attempted": False, "order_send_called": False, "order_check_called": False},
    )
    if audit_logger is not None:
        audit_logger.append_event(event)
    database.insert_event(event)
