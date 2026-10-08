"""Structured error hierarchy.

The project's generic `except Exception` handlers turn every failure into
`CONFIG_ERROR`/`PAPER_STATE_ERROR`, which is why a concrete fault (an invalid
risk distance, an unparseable timestamp) reaches the operator as an opaque
status. These types carry the cause instead, and `as_dict()` produces the record
the telemetry layer stores.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ..clock import Clock, resolve_clock
from ..safety import SafetyEnvelope


class OperationalError(Exception):
    """Base class. Carries cause, source, time and whether recovery is possible."""

    error_type = "OPERATIONAL_ERROR"
    recoverable = False

    def __init__(
        self,
        message: str,
        *,
        source: str = "",
        recoverable: bool | None = None,
        detail: Mapping[str, Any] | None = None,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.source = source
        self.detail: dict[str, Any] = dict(detail or {})
        self.timestamp_utc = resolve_clock(clock).now_utc()
        if recoverable is not None:
            self.recoverable = recoverable

    def as_dict(self) -> dict[str, Any]:
        record = {
            "error_type": self.error_type,
            "message": self.message,
            "source": self.source,
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "recoverable": bool(self.recoverable),
            "detail": dict(self.detail),
        }
        return SafetyEnvelope().seal(record)


class DataError(OperationalError):
    error_type = "DATA_ERROR"
    recoverable = True


class TimestampError(DataError):
    error_type = "TIMESTAMP_ERROR"
    recoverable = True


class InstrumentError(OperationalError):
    error_type = "INSTRUMENT_ERROR"
    recoverable = False


class ConfigurationError(OperationalError):
    error_type = "CONFIGURATION_ERROR"
    recoverable = False


class RiskError(OperationalError):
    error_type = "RISK_ERROR"
    recoverable = False


class PaperStateError(OperationalError):
    error_type = "PAPER_STATE_ERROR"
    recoverable = True


class ExecutionSimulationError(OperationalError):
    error_type = "EXECUTION_SIMULATION_ERROR"
    recoverable = True


class EvidenceError(OperationalError):
    error_type = "EVIDENCE_ERROR"
    recoverable = True


def error_record(
    error: BaseException,
    *,
    source: str = "",
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Build a structured record for any exception.

    An unclassified exception keeps its own type name rather than collapsing
    into a generic CONFIG_ERROR, so the real cause survives into telemetry.
    """

    if isinstance(error, OperationalError):
        record = error.as_dict()
        if source and not record["source"]:
            record["source"] = source
        return record
    now: datetime = resolve_clock(clock).now_utc().astimezone(timezone.utc)
    return SafetyEnvelope().seal(
        {
            "error_type": f"UNCLASSIFIED_{type(error).__name__.upper()}",
            "message": str(error),
            "source": source,
            "timestamp_utc": now.isoformat(),
            "recoverable": False,
            "detail": {},
        }
    )
