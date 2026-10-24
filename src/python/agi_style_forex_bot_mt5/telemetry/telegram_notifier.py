"""Fail-safe Telegram notification path backed by a durable outbox."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

import requests

from agi_style_forex_bot_mt5.contracts import Event
from agi_style_forex_bot_mt5.telemetry.database import TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry.logger_setup import (
    event_to_record,
    redact_text,
)


IMPORTANT_EVENT_TYPES = {
    "ACCOUNT_SNAPSHOT",
    "BOT_STARTED",
    "BOT_STOPPED",
    "CRITICAL_ERROR",
    "FORWARD_SHADOW_STARTED",
    "FORWARD_SHADOW_STOPPED",
    "ORDER_SENT",
    "ORDER_FILLED",
    "PAPER_CYCLE_RESUMED",
    "POSITION_CLOSED",
    "RISK_REJECTED",
    "SHADOW_ORDER_CREATED",
    "SIGNAL_DETECTED",
    "SIGNAL_REJECTED",
}
IMPORTANT_SEVERITIES = {"WARNING", "ERROR", "CRITICAL"}


@dataclass(frozen=True)
class TelegramResult:
    """Outcome of one Telegram notification attempt."""

    queued: bool
    sent: bool
    status: str
    telegram_message_id: str | None = None
    error: str | None = None


Sender = Callable[[str, Mapping[str, Any], float], requests.Response]


def default_sender(url: str, payload: Mapping[str, Any], timeout: float) -> requests.Response:
    return requests.post(url, json=payload, timeout=timeout)


class TelegramNotifier:
    """Send important events to Telegram without breaking the caller on failure."""

    def __init__(
        self,
        *,
        database: TelemetryDatabase | None = None,
        enabled: bool = False,
        bot_token: str | None = None,
        chat_id: str | None = None,
        timeout_seconds: float = 5.0,
        sender: Sender = default_sender,
        max_retry_seconds: int = 3600,
    ) -> None:
        self.database = database
        self.enabled = enabled
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.timeout_seconds = timeout_seconds
        self.sender = sender
        self.max_retry_seconds = max_retry_seconds

    @classmethod
    def from_env(
        cls,
        *,
        database: TelemetryDatabase | None = None,
        enabled: bool = False,
        sender: Sender = default_sender,
    ) -> "TelegramNotifier":
        return cls(database=database, enabled=enabled, sender=sender)

    def should_notify(self, event: Event | Mapping[str, Any]) -> bool:
        record = event_to_record(event)
        return (
            str(record.get("severity")) in IMPORTANT_SEVERITIES
            or str(record.get("event_type")) in IMPORTANT_EVENT_TYPES
        )

    def notify_event(self, event: Event | Mapping[str, Any]) -> TelegramResult:
        """Queue and optionally send an important event, swallowing send failures."""

        record = event_to_record(event)
        if not self.should_notify(record):
            return TelegramResult(queued=False, sent=False, status="SKIPPED")

        message = self._format_message(record)
        telegram_key = f"telegram:{record.get('idempotency_key') or record.get('event_id')}"
        chat_id_redacted = redact_text(str(self.chat_id)) if self.chat_id else None
        telegram_message_id: str | None = None
        if self.database is not None:
            telegram_message_id = self.database.enqueue_telegram_message(
                event_id=str(record.get("event_id") or ""),
                idempotency_key=telegram_key,
                message=message,
                chat_id_redacted=chat_id_redacted,
                payload=record,
            )

        if not self.enabled:
            if self.database is not None and telegram_message_id is not None:
                self.database.mark_telegram_status(telegram_message_id, status="DISABLED")
            return TelegramResult(
                queued=telegram_message_id is not None,
                sent=False,
                status="DISABLED",
                telegram_message_id=telegram_message_id,
            )

        if not self.bot_token or not self.chat_id:
            error = "Telegram credentials missing"
            return self._fail(telegram_message_id, error, retry_after_seconds=300)

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        try:
            response = self.sender(url, payload, self.timeout_seconds)
            if response.status_code == 200:
                if self.database is not None and telegram_message_id is not None:
                    self.database.record_delivery_attempt(
                        telegram_message_id,
                        status="SENT",
                        http_status=response.status_code,
                    )
                return TelegramResult(
                    queued=telegram_message_id is not None,
                    sent=True,
                    status="SENT",
                    telegram_message_id=telegram_message_id,
                )

            retry_after = self._retry_after(response)
            error = f"Telegram HTTP {response.status_code}: {redact_text(response.text)}"
            return self._fail(
                telegram_message_id,
                error,
                http_status=response.status_code,
                retry_after_seconds=retry_after,
            )
        except requests.RequestException as exc:
            return self._fail(telegram_message_id, redact_text(str(exc)), retry_after_seconds=60)

    def send_text(self, *, idempotency_key: str, text: str,
                  payload: Mapping[str, Any] | None = None) -> TelegramResult:
        """Send a preformatted message once per ``idempotency_key`` through the durable outbox.

        Nothing is queued while Telegram is disabled, so enabling it later sends
        every message not sent yet. A key already sent is skipped, so a rerun
        never repeats a message. A failed one is retried with the text stored
        when it was first queued, so the outbox holds what was delivered.
        """

        if not self.enabled:
            return TelegramResult(queued=False, sent=False, status="DISABLED")
        message = redact_text(text)[:3900]
        stored = self.database.telegram_queued(idempotency_key) if self.database is not None else None
        if stored is not None:
            if stored[0] == "SENT":
                return TelegramResult(queued=True, sent=True, status="SKIPPED")
            message = stored[1]
        chat_id_redacted = redact_text(str(self.chat_id)) if self.chat_id else None
        telegram_message_id: str | None = None
        if self.database is not None:
            telegram_message_id = self.database.enqueue_telegram_message(
                event_id=idempotency_key,
                idempotency_key=idempotency_key,
                message=message,
                chat_id_redacted=chat_id_redacted,
                payload=payload or {},
            )
        if not self.bot_token or not self.chat_id:
            return self._fail(telegram_message_id, "Telegram credentials missing", retry_after_seconds=300)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            response = self.sender(url, {"chat_id": self.chat_id, "text": message, "disable_web_page_preview": True},
                                   self.timeout_seconds)
        except requests.RequestException as exc:
            return self._fail(telegram_message_id, redact_text(str(exc)), retry_after_seconds=60)
        if response.status_code == 200:
            if self.database is not None and telegram_message_id is not None:
                self.database.record_delivery_attempt(telegram_message_id, status="SENT",
                                                      http_status=response.status_code)
            return TelegramResult(queued=telegram_message_id is not None, sent=True, status="SENT",
                                  telegram_message_id=telegram_message_id)
        return self._fail(telegram_message_id, f"Telegram HTTP {response.status_code}: {redact_text(response.text)}",
                          http_status=response.status_code, retry_after_seconds=self._retry_after(response))

    def _fail(
        self,
        telegram_message_id: str | None,
        error: str,
        *,
        http_status: int | None = None,
        retry_after_seconds: int = 60,
    ) -> TelegramResult:
        retry_after_seconds = min(max(1, retry_after_seconds), self.max_retry_seconds)
        next_retry = (
            datetime.now(timezone.utc) + timedelta(seconds=retry_after_seconds)
        ).isoformat()
        redacted_error = redact_text(error)
        if self.database is not None and telegram_message_id is not None:
            self.database.record_delivery_attempt(
                telegram_message_id,
                status="FAILED",
                http_status=http_status,
                retry_after_seconds=retry_after_seconds,
                error=redacted_error,
                next_retry_at_utc=next_retry,
            )
        return TelegramResult(
            queued=telegram_message_id is not None,
            sent=False,
            status="FAILED",
            telegram_message_id=telegram_message_id,
            error=redacted_error,
        )

    def _retry_after(self, response: requests.Response) -> int:
        if response.status_code == 429:
            try:
                data = response.json()
                retry_after = int(data.get("parameters", {}).get("retry_after", 60))
                return min(max(1, retry_after), self.max_retry_seconds)
            except (ValueError, TypeError, AttributeError):
                pass
        return 60

    def _format_message(self, record: Mapping[str, Any]) -> str:
        severity = record.get("severity", "INFO")
        event_type = record.get("event_type", "EVENT")
        module = record.get("module", "telemetry")
        signal_id = record.get("signal_id") or record.get("correlation_id") or ""
        symbol = record.get("symbol") or ""
        message = record.get("message") or ""
        parts = [
            f"[{severity}] {event_type}",
            f"module={module}",
        ]
        if signal_id:
            parts.append(f"signal_id={signal_id}")
        if symbol:
            parts.append(f"symbol={symbol}")
        if message:
            parts.append(str(message))
        parts.extend(_reason_parts(record.get("payload_json")))
        return redact_text(" | ".join(parts))[:3900]


# Payload fields that tell the operator why a lifecycle event happened.
REASON_FIELDS = ("reject_code", "reason", "stop_reason", "skipped_cycles", "last_skip_reason")


def _reason_parts(payload_json: Any) -> list[str]:
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else {}
    except ValueError:
        return []
    if not isinstance(payload, Mapping):
        return []
    return [f"{field}={payload[field]}" for field in REASON_FIELDS
            if isinstance(payload.get(field), (str, int)) and not isinstance(payload.get(field), bool)
            and str(payload.get(field)) != ""]
