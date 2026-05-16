"""Canonical audit event with optional hash chaining."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Mapping
from uuid import uuid4

from agi_style_forex_bot_mt5.telemetry.logger_setup import compact_json, redact_secrets, utc_now_iso


@dataclass(frozen=True)
class AuditEvent:
    """Canonical replayable audit event."""

    event_id: str
    idempotency_key: str
    event_type: str
    severity: str
    timestamp_utc: str
    source_module: str
    mode: str
    payload: Mapping[str, Any]
    schema_version: str = "1.0"
    symbol: str | None = None
    signal_id: str | None = None
    paper_trade_id: str | None = None
    previous_event_hash: str | None = None
    event_hash: str = field(default="")

    @staticmethod
    def create(
        *,
        event_type: str,
        severity: str,
        source_module: str,
        mode: str,
        payload: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        previous_event_hash: str | None = None,
        symbol: str | None = None,
        signal_id: str | None = None,
        paper_trade_id: str | None = None,
    ) -> "AuditEvent":
        event_id = f"aevt_{uuid4().hex}"
        event = AuditEvent(
            event_id=event_id,
            idempotency_key=idempotency_key or event_id,
            event_type=event_type,
            severity=severity,
            timestamp_utc=utc_now_iso(),
            source_module=source_module,
            mode=mode,
            payload=redact_secrets(dict(payload or {})),
            symbol=symbol,
            signal_id=signal_id,
            paper_trade_id=paper_trade_id,
            previous_event_hash=previous_event_hash,
        )
        return event.with_hash()

    def canonical_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("event_hash", None)
        return data

    def compute_hash(self) -> str:
        return sha256(compact_json(self.canonical_payload()).encode("utf-8")).hexdigest()

    def with_hash(self) -> "AuditEvent":
        data = asdict(self)
        data["event_hash"] = self.compute_hash()
        return AuditEvent(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return compact_json(self.to_dict())

    @staticmethod
    def from_json(payload: str) -> "AuditEvent":
        data = json.loads(payload)
        event = AuditEvent(**data)
        if event.event_hash and event.event_hash != event.compute_hash():
            raise ValueError("audit event hash mismatch")
        return event

