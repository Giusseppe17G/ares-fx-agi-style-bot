"""Append-only JSONL audit logging and secret redaction."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.contracts import Event


SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "chat_id",
    "account",
    "login",
    "server",
    "path",
    "directory",
    "file",
)

TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
LONG_IDENTIFIER_RE = re.compile(r"\b\d{6,}\b")
ISO_TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b")
WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s\"']+")
POSIX_HOME_PATH_RE = re.compile(r"(?<!\w)/(?:Users|home)/[^\s\"']+")


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return value


def _mask(value: Any) -> str:
    text = str(value)
    suffix = text[-4:] if len(text) >= 4 else ""
    return f"[REDACTED:{suffix}]" if suffix else "[REDACTED]"


def redact_text(text: str) -> str:
    """Redact tokens, long account-like identifiers and local paths in text."""

    protected: dict[str, str] = {}

    def _protect(match: re.Match[str]) -> str:
        token = f"__ISO_TIMESTAMP_{len(protected)}__"
        protected[token] = match.group(0)
        return token

    text = ISO_TIMESTAMP_RE.sub(_protect, text)
    redacted = TELEGRAM_TOKEN_RE.sub("[REDACTED:telegram_token]", text)
    redacted = WINDOWS_PATH_RE.sub("[REDACTED:path]", redacted)
    redacted = POSIX_HOME_PATH_RE.sub("[REDACTED:path]", redacted)
    redacted = LONG_IDENTIFIER_RE.sub(lambda match: _mask(match.group(0)), redacted)
    for token, value in protected.items():
        redacted = redacted.replace(token, value)
    return redacted


def redact_identifier(value: Any) -> str:
    """Keep non-sensitive identifiers readable, hash identifiers that leak secrets."""

    text = str(value)
    redacted = redact_text(text)
    if redacted == text:
        return text
    digest = sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"redacted:{digest}"


def redact_secrets(value: Any, *, parent_key: str = "") -> Any:
    """Recursively redact sensitive values from mappings, lists and strings."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                redacted[key_text] = _mask(item)
            else:
                redacted[key_text] = redact_secrets(item, parent_key=key_text)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item, parent_key=parent_key) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item, parent_key=parent_key) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def compact_json(value: Any) -> str:
    """Serialize a value as deterministic compact JSON."""

    return json.dumps(
        _to_jsonable(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def event_to_record(event: Event | Mapping[str, Any]) -> dict[str, Any]:
    """Convert an Event or event-like mapping into the canonical log record."""

    if isinstance(event, Event):
        payload = redact_secrets(dict(event.payload))
        return {
            "event_id": event.event_id,
            "schema_version": event.schema_version,
            "correlation_id": event.correlation_id,
            "causation_id": event.causation_id,
            "idempotency_key": redact_identifier(event.idempotency_key),
            "sequence_number": event.sequence_number,
            "run_id": event.run_id,
            "environment": event.environment.value,
            "timestamp_utc": event.timestamp_utc.astimezone(timezone.utc).isoformat(),
            "severity": event.severity.value,
            "module": event.module,
            "event_type": event.event_type,
            "signal_id": event.signal_id,
            "symbol": event.symbol,
            "message": redact_text(event.message),
            "payload_json": compact_json(payload),
        }

    raw = dict(event)
    payload = raw.pop("payload", None)
    payload_json = raw.pop("payload_json", None)
    if payload_json is not None:
        try:
            payload = json.loads(str(payload_json))
        except json.JSONDecodeError:
            payload = {"raw_payload_json": str(payload_json)}
    if payload is None:
        payload = {}

    record = {str(key): _to_jsonable(value) for key, value in raw.items()}
    if "idempotency_key" in record:
        record["idempotency_key"] = redact_identifier(record["idempotency_key"])
    if "timestamp_utc" not in record:
        record["timestamp_utc"] = utc_now_iso()
    record["message"] = redact_text(str(record.get("message", "")))
    record["payload_json"] = compact_json(redact_secrets(payload))
    return redact_secrets(record)


class JsonlAuditLogger:
    """Append-only daily JSONL writer for local audit events."""

    def __init__(self, log_dir: str | Path = "data/logs", max_file_mb: int = 50) -> None:
        self.log_dir = Path(log_dir)
        self.max_file_bytes = max(1, int(max_file_mb)) * 1024 * 1024

    def _path_for_today(self) -> Path:
        today = datetime.now(timezone.utc).date().isoformat()
        base = self.log_dir / f"events-{today}.jsonl"
        if not base.exists() or base.stat().st_size < self.max_file_bytes:
            return base

        index = 1
        while True:
            rotated = self.log_dir / f"events-{today}-{index}.jsonl"
            if not rotated.exists() or rotated.stat().st_size < self.max_file_bytes:
                return rotated
            index += 1

    def append_event(self, event: Event | Mapping[str, Any]) -> Path:
        """Append one valid JSON object line and return the file path."""

        self.log_dir.mkdir(parents=True, exist_ok=True)
        record = event_to_record(event)
        line = compact_json(record)
        target = self._path_for_today()
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.write("\n")
            handle.flush()
        return target
