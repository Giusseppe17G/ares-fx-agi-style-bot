"""SQLite persistence for audit events, domain telemetry and Telegram outbox."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from agi_style_forex_bot_mt5.contracts import Event
from agi_style_forex_bot_mt5.telemetry.logger_setup import (
    compact_json,
    event_to_record,
    redact_secrets,
    utc_now_iso,
)


DOMAIN_TABLES = {
    "signals",
    "orders",
    "trades",
    "errors",
    "account_snapshots",
    "risk_events",
    "broker_quality",
    "model_predictions",
    "backtest_results",
}


class TelemetryDatabase:
    """Small SQLite adapter with versioned migrations and idempotent inserts."""

    def __init__(self, path: str | Path = "data/telemetry.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            pass
        self.migrate()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TelemetryDatabase":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def migrate(self) -> None:
        """Apply idempotent schema migrations."""

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at_utc TEXT NOT NULL
            )
            """
        )
        if not self._migration_applied(1):
            self._apply_v1()
            self._conn.execute(
                "INSERT INTO schema_migrations(version, applied_at_utc) VALUES (?, ?)",
                (1, utc_now_iso()),
            )
        self._apply_paper_tables()
        self._apply_observability_tables()
        self._conn.commit()

    def _migration_applied(self, version: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
        ).fetchone()
        return row is not None

    def _apply_v1(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                schema_version TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                causation_id TEXT,
                idempotency_key TEXT NOT NULL UNIQUE,
                sequence_number INTEGER,
                run_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                severity TEXT NOT NULL,
                module TEXT NOT NULL,
                event_type TEXT NOT NULL,
                signal_id TEXT,
                symbol TEXT,
                message TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_signal ON events(signal_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")

        for table in DOMAIN_TABLES:
            self._conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT,
                    signal_id TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    timestamp_utc TEXT NOT NULL,
                    symbol TEXT,
                    status TEXT,
                    payload_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_signal ON {table}(signal_id)"
            )

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_message_id TEXT NOT NULL UNIQUE,
                event_id TEXT,
                idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at_utc TEXT,
                last_error TEXT,
                chat_id_redacted TEXT,
                message_redacted TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_outbox_status ON telegram_outbox(status)"
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS delivery_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_message_id TEXT NOT NULL,
                attempted_at_utc TEXT NOT NULL,
                status TEXT NOT NULL,
                http_status INTEGER,
                retry_after_seconds INTEGER,
                error TEXT,
                FOREIGN KEY (telegram_message_id)
                    REFERENCES telegram_outbox(telegram_message_id)
                    ON DELETE CASCADE
            )
            """
        )

    def _apply_paper_tables(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_trade_id TEXT NOT NULL UNIQUE,
                signal_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                opened_at_utc TEXT NOT NULL,
                closed_at_utc TEXT,
                updated_at_utc TEXT NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol ON paper_trades(symbol)")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trade_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_trade_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_performance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id TEXT NOT NULL UNIQUE,
                timestamp_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS forward_shadow_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                started_at_utc TEXT NOT NULL,
                stopped_at_utc TEXT,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )

    def _apply_observability_tables(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                heartbeat_id TEXT NOT NULL UNIQUE,
                timestamp_utc TEXT NOT NULL,
                mode TEXT NOT NULL,
                mt5_connected INTEGER NOT NULL,
                execution_attempted INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_heartbeats_time ON heartbeats(timestamp_utc)")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT NOT NULL UNIQUE,
                alert_code TEXT NOT NULL,
                severity TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                deduplication_key TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_code ON alerts(alert_code)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_dedup ON alerts(deduplication_key, timestamp_utc)")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command_id TEXT NOT NULL UNIQUE,
                chat_id_redacted TEXT NOT NULL,
                command TEXT NOT NULL,
                status TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                response_text TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operational_state (
                state_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary_id TEXT NOT NULL UNIQUE,
                summary_date TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL UNIQUE,
                severity TEXT NOT NULL,
                incident_code TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )

    def insert_event(self, event: Event | Mapping[str, Any]) -> bool:
        """Insert an event once by event_id and idempotency_key."""

        record = event_to_record(event)
        params = {
            "event_id": str(record.get("event_id") or f"evt_{uuid4().hex}"),
            "schema_version": str(record.get("schema_version") or "1.0"),
            "correlation_id": str(record.get("correlation_id") or record["event_id"]),
            "causation_id": record.get("causation_id"),
            "idempotency_key": str(record.get("idempotency_key") or record["event_id"]),
            "sequence_number": record.get("sequence_number"),
            "run_id": str(record.get("run_id") or "unknown"),
            "environment": str(record.get("environment") or "BACKTEST"),
            "timestamp_utc": str(record.get("timestamp_utc") or utc_now_iso()),
            "severity": str(record.get("severity") or "INFO"),
            "module": str(record.get("module") or "telemetry"),
            "event_type": str(record.get("event_type") or "EVENT"),
            "signal_id": record.get("signal_id"),
            "symbol": record.get("symbol"),
            "message": str(record.get("message") or ""),
            "payload_json": str(record.get("payload_json") or "{}"),
            "created_at_utc": utc_now_iso(),
        }
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO events (
                event_id, schema_version, correlation_id, causation_id,
                idempotency_key, sequence_number, run_id, environment,
                timestamp_utc, severity, module, event_type, signal_id, symbol,
                message, payload_json, created_at_utc
            ) VALUES (
                :event_id, :schema_version, :correlation_id, :causation_id,
                :idempotency_key, :sequence_number, :run_id, :environment,
                :timestamp_utc, :severity, :module, :event_type, :signal_id,
                :symbol, :message, :payload_json, :created_at_utc
            )
            """,
            params,
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def insert_record(
        self,
        table: str,
        record: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> bool:
        """Insert a domain telemetry record once by idempotency_key."""

        if table not in DOMAIN_TABLES:
            raise ValueError(f"unsupported telemetry table: {table}")

        redacted = redact_secrets(dict(record))
        key = idempotency_key or str(redacted.get("idempotency_key") or uuid4().hex)
        payload_json = compact_json(redacted)
        params = {
            "record_id": redacted.get("record_id")
            or redacted.get("event_id")
            or redacted.get("order_id")
            or redacted.get("trade_id")
            or redacted.get("run_id"),
            "signal_id": redacted.get("signal_id"),
            "idempotency_key": key,
            "timestamp_utc": str(redacted.get("timestamp_utc") or utc_now_iso()),
            "symbol": redacted.get("symbol"),
            "status": redacted.get("status"),
            "payload_json": payload_json,
            "created_at_utc": utc_now_iso(),
        }
        cursor = self._conn.execute(
            f"""
            INSERT OR IGNORE INTO {table} (
                record_id, signal_id, idempotency_key, timestamp_utc, symbol,
                status, payload_json, created_at_utc
            ) VALUES (
                :record_id, :signal_id, :idempotency_key, :timestamp_utc, :symbol,
                :status, :payload_json, :created_at_utc
            )
            """,
            params,
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def enqueue_telegram_message(
        self,
        *,
        event_id: str | None,
        idempotency_key: str,
        message: str,
        chat_id_redacted: str | None,
        payload: Mapping[str, Any] | None = None,
    ) -> str:
        """Durably enqueue a Telegram message and return its local message id."""

        existing = self._conn.execute(
            "SELECT telegram_message_id FROM telegram_outbox WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            return str(existing["telegram_message_id"])

        now = utc_now_iso()
        telegram_message_id = f"tg_{uuid4().hex}"
        self._conn.execute(
            """
            INSERT INTO telegram_outbox (
                telegram_message_id, event_id, idempotency_key, status,
                attempt_count, next_retry_at_utc, last_error, chat_id_redacted,
                message_redacted, payload_json, created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, 'PENDING', 0, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                telegram_message_id,
                event_id,
                idempotency_key,
                now,
                chat_id_redacted,
                message,
                compact_json(redact_secrets(payload or {})),
                now,
                now,
            ),
        )
        self._conn.commit()
        return telegram_message_id

    def record_delivery_attempt(
        self,
        telegram_message_id: str,
        *,
        status: str,
        http_status: int | None = None,
        retry_after_seconds: int | None = None,
        error: str | None = None,
        next_retry_at_utc: str | None = None,
    ) -> None:
        """Record one Telegram attempt and update the outbox state."""

        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO delivery_attempts (
                telegram_message_id, attempted_at_utc, status, http_status,
                retry_after_seconds, error
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (telegram_message_id, now, status, http_status, retry_after_seconds, error),
        )
        self._conn.execute(
            """
            UPDATE telegram_outbox
            SET status = ?,
                attempt_count = attempt_count + 1,
                next_retry_at_utc = ?,
                last_error = ?,
                updated_at_utc = ?
            WHERE telegram_message_id = ?
            """,
            (status, next_retry_at_utc, error, now, telegram_message_id),
        )
        self._conn.commit()

    def mark_telegram_status(
        self,
        telegram_message_id: str,
        *,
        status: str,
        last_error: str | None = None,
        next_retry_at_utc: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE telegram_outbox
            SET status = ?, last_error = ?, next_retry_at_utc = ?, updated_at_utc = ?
            WHERE telegram_message_id = ?
            """,
            (status, last_error, next_retry_at_utc, utc_now_iso(), telegram_message_id),
        )
        self._conn.commit()

    def insert_paper_trade(self, trade: Mapping[str, Any]) -> bool:
        payload = redact_secrets(dict(trade))
        now = utc_now_iso()
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO paper_trades (
                paper_trade_id, signal_id, idempotency_key, symbol, status,
                payload_json, opened_at_utc, closed_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["paper_trade_id"],
                payload.get("signal_id", ""),
                payload["idempotency_key"],
                payload["symbol"],
                payload["status"],
                compact_json(payload),
                payload.get("entry_time_utc") or now,
                payload.get("exit_time_utc"),
                now,
            ),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def update_paper_trade(self, trade: Mapping[str, Any]) -> None:
        payload = redact_secrets(dict(trade))
        self._conn.execute(
            """
            UPDATE paper_trades
            SET status = ?, payload_json = ?, closed_at_utc = ?, updated_at_utc = ?
            WHERE paper_trade_id = ?
            """,
            (
                payload["status"],
                compact_json(payload),
                payload.get("exit_time_utc"),
                utc_now_iso(),
                payload["paper_trade_id"],
            ),
        )
        self._conn.commit()

    def insert_paper_trade_event(self, paper_trade_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO paper_trade_events (
                paper_trade_id, event_type, timestamp_utc, payload_json
            ) VALUES (?, ?, ?, ?)
            """,
            (paper_trade_id, event_type, utc_now_iso(), compact_json(redact_secrets(payload))),
        )
        self._conn.commit()

    def fetch_open_paper_trades(self) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM paper_trades WHERE status = 'OPEN' ORDER BY id"
            )
        )

    def fetch_paper_trades(self) -> list[sqlite3.Row]:
        return list(self._conn.execute("SELECT * FROM paper_trades ORDER BY id"))

    def fetch_paper_trade_by_idempotency(self, idempotency_key: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM paper_trades WHERE idempotency_key = ? ORDER BY id LIMIT 1",
            (idempotency_key,),
        ).fetchone()

    def insert_heartbeat(self, payload: Mapping[str, Any]) -> bool:
        raw = dict(payload)
        safe = redact_secrets(raw)
        now = str(raw.get("timestamp_utc") or utc_now_iso())
        safe["timestamp_utc"] = now
        heartbeat_id = str(safe.get("heartbeat_id") or f"hb_{uuid4().hex}")
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO heartbeats (
                heartbeat_id, timestamp_utc, mode, mt5_connected,
                execution_attempted, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                heartbeat_id,
                now,
                str(safe.get("mode") or "unknown"),
                1 if bool(safe.get("mt5_connected", False)) else 0,
                1 if bool(safe.get("execution_attempted", False)) else 0,
                compact_json(safe),
            ),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def insert_alert(self, payload: Mapping[str, Any], *, dedup_window_seconds: int = 300) -> bool:
        raw = dict(payload)
        safe = redact_secrets(raw)
        now = str(raw.get("timestamp_utc") or utc_now_iso())
        safe["timestamp_utc"] = now
        key = str(safe.get("deduplication_key") or safe.get("alert_code") or "alert")
        existing = self._conn.execute(
            """
            SELECT timestamp_utc FROM alerts
            WHERE deduplication_key = ?
            ORDER BY timestamp_utc DESC
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        if existing is not None:
            try:
                from datetime import datetime

                previous = datetime.fromisoformat(str(existing["timestamp_utc"]))
                current = datetime.fromisoformat(now)
                if (current - previous).total_seconds() < dedup_window_seconds:
                    return False
            except ValueError:
                pass
        alert_id = str(safe.get("alert_id") or f"alt_{uuid4().hex}")
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO alerts (
                alert_id, alert_code, severity, timestamp_utc,
                deduplication_key, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                str(safe.get("alert_code") or "ALERT"),
                str(safe.get("severity") or "WARNING"),
                now,
                key,
                compact_json(safe),
            ),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def get_latest_health(self) -> dict[str, Any]:
        heartbeat = self._conn.execute("SELECT * FROM heartbeats ORDER BY id DESC LIMIT 1").fetchone()
        state = self.get_operational_state()
        alerts = [
            json.loads(row["payload_json"])
            for row in self._conn.execute("SELECT payload_json FROM alerts ORDER BY id DESC LIMIT 10")
        ]
        payload = json.loads(heartbeat["payload_json"]) if heartbeat is not None else {}
        return {
            "mode": payload.get("mode", "unknown"),
            "last_heartbeat_utc": payload.get("timestamp_utc"),
            "mt5_connected": bool(payload.get("mt5_connected", False)),
            "shadow_paused": bool(state.get("shadow_paused", False)),
            "open_paper_trades": payload.get("open_paper_trades", 0),
            "recent_alerts": alerts,
            "execution_attempted": False,
        }

    def get_operational_state(self) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT payload_json FROM operational_state WHERE state_key = 'runtime'"
        ).fetchone()
        if row is None:
            return {
                "shadow_paused": False,
                "paused_reason": "",
                "paused_by": "",
                "paused_at_utc": None,
                "resumed_at_utc": None,
                "last_heartbeat_utc": None,
                "last_daily_summary_utc": None,
                "last_incident_utc": None,
                "execution_attempted": False,
            }
        return json.loads(row["payload_json"])

    def set_shadow_paused(self, paused: bool, *, reason: str, paused_by: str) -> dict[str, Any]:
        state = self.get_operational_state()
        now = utc_now_iso()
        state.update(
            {
                "shadow_paused": bool(paused),
                "paused_reason": reason if paused else "",
                "paused_by": paused_by if paused else state.get("paused_by", ""),
                "execution_attempted": False,
            }
        )
        if paused:
            state["paused_at_utc"] = now
        else:
            state["resumed_at_utc"] = now
        self._conn.execute(
            """
            INSERT INTO operational_state (state_key, payload_json, updated_at_utc)
            VALUES ('runtime', ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at_utc = excluded.updated_at_utc
            """,
            (compact_json(redact_secrets(state)), now),
        )
        self._conn.commit()
        return state

    def get_shadow_paused(self) -> bool:
        return bool(self.get_operational_state().get("shadow_paused", False))

    def update_operational_state(self, updates: Mapping[str, Any]) -> dict[str, Any]:
        state = self.get_operational_state()
        raw_updates = dict(updates)
        state.update(redact_secrets(raw_updates))
        for key, value in raw_updates.items():
            if key.endswith("_utc"):
                state[key] = value
        state["execution_attempted"] = False
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO operational_state (state_key, payload_json, updated_at_utc)
            VALUES ('runtime', ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at_utc = excluded.updated_at_utc
            """,
            (compact_json(state), now),
        )
        self._conn.commit()
        return state

    def insert_telegram_command(self, payload: Mapping[str, Any]) -> bool:
        safe = redact_secrets(dict(payload))
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO telegram_commands (
                command_id, chat_id_redacted, command, status,
                timestamp_utc, response_text, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(safe.get("command_id") or f"tgc_{uuid4().hex}"),
                str(safe.get("chat_id_redacted") or ""),
                str(safe.get("command") or ""),
                str(safe.get("status") or "UNKNOWN"),
                str(safe.get("timestamp_utc") or utc_now_iso()),
                str(safe.get("response_text") or ""),
                compact_json(safe),
            ),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def insert_daily_summary(self, payload: Mapping[str, Any]) -> bool:
        safe = redact_secrets(dict(payload))
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO daily_summaries (
                summary_id, summary_date, timestamp_utc, payload_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                str(safe.get("summary_id") or f"ds_{uuid4().hex}"),
                str(safe.get("summary_date") or ""),
                str(safe.get("timestamp_utc") or utc_now_iso()),
                compact_json(safe),
            ),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def insert_incident(self, payload: Mapping[str, Any]) -> bool:
        safe = redact_secrets(dict(payload))
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO incidents (
                incident_id, severity, incident_code, timestamp_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(safe.get("incident_id") or f"inc_{uuid4().hex}"),
                str(safe.get("severity") or "WARNING"),
                str(safe.get("incident_code") or "INCIDENT"),
                str(safe.get("timestamp_utc") or utc_now_iso()),
                compact_json(safe),
            ),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def count_rows(self, table: str) -> int:
        if table not in DOMAIN_TABLES and table not in {
            "events",
            "telegram_outbox",
            "delivery_attempts",
            "schema_migrations",
            "paper_trades",
            "paper_trade_events",
            "paper_performance_snapshots",
            "forward_shadow_sessions",
            "heartbeats",
            "alerts",
            "telegram_commands",
            "operational_state",
            "daily_summaries",
            "incidents",
        }:
            raise ValueError(f"unsupported telemetry table: {table}")
        row = self._conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])

    def fetch_all(self, table: str) -> list[sqlite3.Row]:
        if table not in DOMAIN_TABLES and table not in {
            "events",
            "telegram_outbox",
            "delivery_attempts",
            "schema_migrations",
            "paper_trades",
            "paper_trade_events",
            "paper_performance_snapshots",
            "forward_shadow_sessions",
            "heartbeats",
            "alerts",
            "telegram_commands",
            "operational_state",
            "daily_summaries",
            "incidents",
        }:
            raise ValueError(f"unsupported telemetry table: {table}")
        return list(self._conn.execute(f"SELECT * FROM {table} ORDER BY id"))

    def fetch_by_idempotency_key(self, table: str, idempotency_key: str) -> sqlite3.Row | None:
        """Fetch one row from a supported table by idempotency key."""

        if table not in DOMAIN_TABLES and table not in {"events", "telegram_outbox"}:
            raise ValueError(f"unsupported telemetry table: {table}")
        return self._conn.execute(
            f"SELECT * FROM {table} WHERE idempotency_key = ? ORDER BY id LIMIT 1",
            (idempotency_key,),
        ).fetchone()

    def table_counts(self, tables: Iterable[str] | None = None) -> dict[str, int]:
        selected = list(tables or ["events", *sorted(DOMAIN_TABLES), "telegram_outbox"])
        return {table: self.count_rows(table) for table in selected}
