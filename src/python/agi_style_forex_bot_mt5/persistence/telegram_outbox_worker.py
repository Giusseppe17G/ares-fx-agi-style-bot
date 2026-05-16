"""Durable Telegram outbox retry worker."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import requests

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry.logger_setup import redact_text


Sender = Callable[[str, Mapping[str, Any], float], requests.Response]


def flush_telegram_outbox(
    *,
    database: TelemetryDatabase,
    bot_token: str | None = None,
    chat_id: str | None = None,
    sender: Sender | None = None,
    timeout_seconds: float = 5.0,
    limit: int = 20,
) -> dict[str, Any]:
    """Retry pending/failed outbox messages once without duplicating delivered rows."""

    sender = sender or _default_sender
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    rows = [row for row in database.fetch_all("telegram_outbox") if row["status"] in {"PENDING", "FAILED"}]
    attempted = 0
    delivered = 0
    failed = 0
    skipped = 0
    for row in rows[:limit]:
        next_retry = row["next_retry_at_utc"]
        if next_retry:
            try:
                if datetime.fromisoformat(str(next_retry)) > datetime.now(timezone.utc):
                    skipped += 1
                    continue
            except ValueError:
                pass
        if not token or not chat:
            database.mark_telegram_status(row["telegram_message_id"], status="FAILED", last_error="Telegram credentials missing")
            failed += 1
            continue
        attempted += 1
        try:
            response = sender(
                f"https://api.telegram.org/bot{token}/sendMessage",
                {"chat_id": chat, "text": row["message_redacted"], "disable_web_page_preview": True},
                timeout_seconds,
            )
            if response.status_code == 200:
                database.record_delivery_attempt(row["telegram_message_id"], status="SENT", http_status=200)
                delivered += 1
            else:
                database.record_delivery_attempt(row["telegram_message_id"], status="FAILED", http_status=response.status_code, error=redact_text(response.text))
                failed += 1
        except requests.RequestException as exc:
            database.record_delivery_attempt(row["telegram_message_id"], status="FAILED", error=redact_text(str(exc)))
            failed += 1
    return {
        "mode": "telegram-outbox-flush",
        "status": "OK" if failed == 0 else "WARNING",
        "pending_before": len(rows),
        "attempted": attempted,
        "delivered": delivered,
        "failed": failed,
        "skipped": skipped,
        "execution_attempted": False,
    }


def _default_sender(url: str, payload: Mapping[str, Any], timeout: float) -> requests.Response:
    return requests.post(url, json=payload, timeout=timeout)

