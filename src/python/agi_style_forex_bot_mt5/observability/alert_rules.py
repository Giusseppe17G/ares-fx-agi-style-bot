"""Operational alert rules for 24/7 forward-shadow runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from uuid import uuid4

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


@dataclass(frozen=True)
class OperationalAlert:
    severity: str
    alert_code: str
    message: str
    recommended_action: str
    deduplication_key: str
    timestamp_utc: str
    metadata: Mapping[str, Any]
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"alert_id": f"alt_{uuid4().hex}", **asdict(self)}


class AlertRuleEngine:
    """Evaluate and persist deduplicated operational alerts."""

    def __init__(self, database: TelemetryDatabase, *, dedup_window_seconds: int = 300) -> None:
        self.database = database
        self.dedup_window_seconds = dedup_window_seconds

    def evaluate(self, metrics: Mapping[str, Any]) -> tuple[OperationalAlert, ...]:
        now = datetime.now(timezone.utc).isoformat()
        alerts: list[OperationalAlert] = []
        if not bool(metrics.get("mt5_connected", False)):
            alerts.append(
                self._alert(
                    now,
                    "CRITICAL",
                    "MT5_DISCONNECTED",
                    "MT5 is disconnected",
                    "Open MT5 over RDP, verify account login and terminal connectivity.",
                    metrics,
                )
            )
        if int(metrics.get("symbols_seen", 0) or 0) > 0 and int(metrics.get("symbols_rejected", 0) or 0) >= int(metrics.get("symbols_seen", 0) or 0):
            alerts.append(
                self._alert(
                    now,
                    "WARNING",
                    "ALL_SYMBOLS_REJECTED",
                    "All configured symbols are rejected",
                    "Run mt5-diagnose and check stale ticks, Market Watch visibility and session status.",
                    metrics,
                )
            )
        if float(metrics.get("drawdown_paper", 0.0) or 0.0) <= -3.0:
            alerts.append(
                self._alert(
                    now,
                    "CRITICAL",
                    "PAPER_DAILY_DRAWDOWN",
                    "Paper drawdown exceeds daily threshold",
                    "Pause new shadow entries and review forward performance.",
                    metrics,
                )
            )
        if str(metrics.get("drift_status", "")) == "PERFORMANCE_DRIFT":
            alerts.append(
                self._alert(
                    now,
                    "WARNING",
                    "PERFORMANCE_DRIFT",
                    "Forward performance drift detected",
                    "Keep strategy in WATCHLIST or REJECTED until research is reviewed.",
                    metrics,
                )
            )
        if str(metrics.get("sqlite_status", "OK")) != "OK":
            alerts.append(
                self._alert(now, "CRITICAL", "SQLITE_UNAVAILABLE", "SQLite unavailable", "Stop forward-shadow until durable audit is restored.", metrics)
            )
        if str(metrics.get("jsonl_status", "OK")) != "OK":
            alerts.append(
                self._alert(now, "CRITICAL", "JSONL_UNAVAILABLE", "JSONL unavailable", "Stop forward-shadow until append-only audit is restored.", metrics)
            )
        if metrics.get("disk_free_gb") is not None and float(metrics.get("disk_free_gb") or 0.0) < 5.0:
            alerts.append(
                self._alert(now, "CRITICAL", "LOW_DISK_SPACE", "Disk free space is low", "Free disk space or rotate logs before continuing unattended operation.", metrics)
            )
        return tuple(alerts)

    def persist(self, alerts: Iterable[OperationalAlert]) -> int:
        emitted = 0
        for alert in alerts:
            if self.database.insert_alert(alert.to_dict(), dedup_window_seconds=self.dedup_window_seconds):
                emitted += 1
        return emitted

    def _alert(
        self,
        timestamp: str,
        severity: str,
        code: str,
        message: str,
        action: str,
        metadata: Mapping[str, Any],
    ) -> OperationalAlert:
        return OperationalAlert(
            severity=severity,
            alert_code=code,
            message=message,
            recommended_action=action,
            deduplication_key=code,
            timestamp_utc=timestamp,
            metadata=dict(metadata),
            execution_attempted=False,
        )
