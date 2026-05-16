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
