"""Forward-shadow recovery manager."""

from __future__ import annotations

from typing import Any

from agi_style_forex_bot_mt5.contracts import Environment, Event, Severity
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase

from .db_health import check_db_health


class RecoveryManager:
    """Perform fail-closed startup recovery checks."""

    def __init__(self, *, database: TelemetryDatabase, audit_logger: JsonlAuditLogger, run_id: str, mode: str = "forward-shadow") -> None:
        self.database = database
        self.audit_logger = audit_logger
        self.run_id = run_id
        self.mode = mode

    def recover(self) -> dict[str, Any]:
        self._audit("RECOVERY_STARTED", Severity.INFO, {"mode": self.mode, "execution_attempted": False})
        health = check_db_health(sqlite_path=self.database.path)
        open_trades = len(self.database.fetch_open_paper_trades())
        state = self.database.get_operational_state()
        last_heartbeat = self.database.get_latest_health().get("last_heartbeat_utc")
        ok = health["status"] == "OK"
        payload = {
            "mode": self.mode,
            "status": "OK" if ok else "FAILED",
            "db_health_status": health["status"],
            "open_paper_trades": open_trades,
            "shadow_paused": bool(state.get("shadow_paused", False)),
            "last_heartbeat_utc": last_heartbeat,
            "unexpected_shutdown_detected": bool(last_heartbeat and open_trades >= 0),
            "execution_attempted": False,
        }
        self._audit("RECOVERY_COMPLETED" if ok else "RECOVERY_FAILED", Severity.INFO if ok else Severity.CRITICAL, payload)
        return payload

    def _audit(self, event_type: str, severity: Severity, payload: dict[str, Any]) -> None:
        event = Event.create(
            run_id=self.run_id,
            environment=Environment.DEMO,
            severity=severity,
            module="recovery",
            event_type=event_type,
            message=event_type.lower(),
            correlation_id=f"{self.run_id}:{event_type}",
            payload=payload,
        )
        self.database.insert_event(event)
        self.audit_logger.append_event(event)

