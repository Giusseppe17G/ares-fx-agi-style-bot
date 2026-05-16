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
        if str(metrics.get("broker_quality_status", "")) == "NOT_READY":
            alerts.append(
                self._alert(now, "CRITICAL", "BROKER_QUALITY_NOT_READY", "Broker quality is not ready", "Review broker-quality report before continuing observation.", metrics)
            )
        if bool(metrics.get("symbol_not_ready", False)):
            alerts.append(
                self._alert(now, "WARNING", "SYMBOL_NOT_READY", "One or more symbols are not ready", "Review symbol readiness scores and reject reasons.", metrics)
            )
        if bool(metrics.get("broker_spread_degraded", False)):
            alerts.append(
                self._alert(now, "WARNING", "BROKER_SPREAD_DEGRADED", "Broker spread quality degraded", "Compare real spreads with broker cost profile and backtest assumptions.", metrics)
            )
        if bool(metrics.get("tick_freshness_degraded", False)):
            alerts.append(
                self._alert(now, "WARNING", "TICK_FRESHNESS_DEGRADED", "Tick freshness degraded", "Run mt5-diagnose and verify market session or broker connectivity.", metrics)
            )
        if bool(metrics.get("mt5_read_latency_high", False)):
            alerts.append(
                self._alert(now, "WARNING", "MT5_READ_LATENCY_HIGH", "MT5 read latency is high", "Check EC2 CPU/memory, network latency and MT5 terminal responsiveness.", metrics)
            )
        if bool(metrics.get("rollover_spread_danger", False)):
            alerts.append(
                self._alert(now, "WARNING", "ROLLOVER_SPREAD_DANGER", "Rollover spread danger detected", "Keep new shadow entries paused near rollover if spreads remain elevated.", metrics)
            )
        if bool(metrics.get("currency_exposure_high", False)):
            alerts.append(
                self._alert(now, "WARNING", "CURRENCY_EXPOSURE_HIGH", "Currency exposure is high", "Avoid adding correlated or same-currency shadow exposure until risk normalizes.", metrics)
            )
        if bool(metrics.get("correlation_cluster_high", False)):
            alerts.append(
                self._alert(now, "WARNING", "CORRELATION_CLUSTER_HIGH", "Correlation cluster exposure is high", "Review open paper trades and reject lower-ranked correlated signals.", metrics)
            )
        if bool(metrics.get("portfolio_risk_budget_low", False)):
            alerts.append(
                self._alert(now, "WARNING", "PORTFOLIO_RISK_BUDGET_LOW", "Portfolio risk budget is low", "Pause or reduce new shadow entries until open risk decreases.", metrics)
            )
        if bool(metrics.get("dynamic_risk_reduced", False)):
            alerts.append(
                self._alert(now, "INFO", "DYNAMIC_RISK_REDUCED", "Dynamic risk allocator reduced shadow risk", "Review drawdown, spread, ML probability and broker readiness context.", metrics)
            )
        if bool(metrics.get("strategy_concentration_high", False)):
            alerts.append(
                self._alert(now, "WARNING", "STRATEGY_CONCENTRATION_HIGH", "Strategy concentration is high", "Prefer diversified validated candidates before opening more paper trades.", metrics)
            )
        if bool(metrics.get("regime_concentration_high", False)):
            alerts.append(
                self._alert(now, "WARNING", "REGIME_CONCENTRATION_HIGH", "Regime concentration is high", "Reduce exposure to a single market regime until conditions diversify.", metrics)
            )
        if str(metrics.get("db_health_status", "OK")) != "OK":
            alerts.append(
                self._alert(now, "CRITICAL", "DB_INTEGRITY_FAILED", "Database health or integrity failed", "Stop forward-shadow until SQLite health is repaired from backup.", metrics)
            )
        if int(metrics.get("event_gap_count", 0) or 0) > 0:
            alerts.append(
                self._alert(now, "WARNING", "AUDIT_EVENT_GAP", "Audit heartbeat gaps detected", "Run audit-replay and inspect restart or connectivity windows.", metrics)
            )
        if int(metrics.get("telegram_outbox_pending", 0) or 0) >= 10:
            alerts.append(
                self._alert(now, "WARNING", "TELEGRAM_OUTBOX_BACKLOG", "Telegram outbox backlog is high", "Run telegram-outbox-flush and verify Telegram connectivity.", metrics)
            )
        if "last_backup_utc" in metrics and not metrics.get("last_backup_utc"):
            alerts.append(
                self._alert(now, "INFO", "BACKUP_STALE", "No recent local backup is recorded", "Run backup and verify data/backups retention.", metrics)
            )
        if bool(metrics.get("recovery_failed", False)):
            alerts.append(
                self._alert(now, "CRITICAL", "RECOVERY_FAILED", "Recovery failed", "Keep bot fail-closed and inspect db-health/audit-replay reports.", metrics)
            )
        if bool(metrics.get("jsonl_rotation_failed", False)):
            alerts.append(
                self._alert(now, "WARNING", "JSONL_ROTATION_FAILED", "JSONL rotation failed", "Check disk permissions and backup availability.", metrics)
            )
        if str(metrics.get("cost_model_status", "OK")) in {"WATCHLIST", "COST_ASSUMPTION_TOO_LOW"}:
            alerts.append(
                self._alert(now, "WARNING", "COST_ASSUMPTION_TOO_LOW", "Cost assumptions may be too low", "Run simulation-calibration and compare broker costs against paper fills.", metrics)
            )
        if int(metrics.get("fill_quality_poor_count", 0) or 0) > 0:
            alerts.append(
                self._alert(now, "WARNING", "FILL_QUALITY_DEGRADED", "Poor paper fill quality detected", "Review spread, slippage and broker readiness before promotion.", metrics)
            )
        if int(metrics.get("ambiguous_intrabar_events", 0) or 0) >= 5:
            alerts.append(
                self._alert(now, "WARNING", "AMBIGUOUS_EVENTS_HIGH", "Ambiguous intrabar events are high", "Treat paper results conservatively and avoid promotion.", metrics)
            )
        if str(metrics.get("paper_vs_backtest_status", "")) in {"BACKTEST_TOO_OPTIMISTIC", "STRATEGY_BEHAVIOR_DRIFT"}:
            alerts.append(
                self._alert(now, "WARNING", "BACKTEST_FORWARD_DIVERGENCE", "Backtest and forward paper results diverge", "Keep strategy in WATCHLIST or reject until recalibrated.", metrics)
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
