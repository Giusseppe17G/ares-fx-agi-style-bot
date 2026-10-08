"""The single halt authority.

Twenty-two modules previously inferred halt state on their own, each with a
different token set, a different field set, different case handling and (in all
but one) no timestamp ordering at all. This detector is the union of those rules
plus the two properties none of them had together: it orders by timestamp and it
takes an injectable clock, so "is the halt active today?" is answerable without
consulting wall-clock time.

Field coverage is the union of every legacy detector:
  event_type, message, halt_reason, alert_code, paused_reason, error,
  latest_exit_reason (only when its value is itself halt-like)
read from both the record root and its payload, case-insensitively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from ..clock import Clock, resolve_clock
from ..safety import SafetyEnvelope
from .states import HALT_PRECEDENCE, HALT_SEVERITY, EvidenceQuality, HaltAge, HaltKind, Severity


DEFAULT_DAILY_DRAWDOWN_LIMIT = -3.0
DEFAULT_STALE_AFTER_DAYS = 7

# Token -> halt kind. Ordered: the first match on a record wins, so an explicit
# cause outranks the generic PAPER_SHADOW_HALTED wrapper the bot emits.
HALT_TOKENS: tuple[tuple[str, HaltKind], ...] = (
    ("PAPER_DAILY_DRAWDOWN_HALT", HaltKind.DAILY_DRAWDOWN),
    ("PAPER_DAILY_DRAWDOWN", HaltKind.DAILY_DRAWDOWN),
    ("PAPER_STATE_ERROR", HaltKind.PAPER_STATE),
    ("CONFIG_ERROR", HaltKind.CONFIG),
    ("SHADOW_MANUALLY_PAUSED", HaltKind.MANUAL),
    ("PAPER_SHADOW_HALTED", HaltKind.UNKNOWN),
)

SCANNED_FIELDS = ("event_type", "message", "halt_reason", "alert_code", "paused_reason", "error")
STATE_VALUE_FIELDS = ("latest_exit_reason",)


@dataclass(frozen=True)
class HaltRecord:
    """One piece of halt evidence, normalized."""

    kind: HaltKind
    reason: str
    timestamp_utc: str
    source: str
    severity: Severity
    matched_field: str
    timestamp_valid: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "halt_kind": self.kind.value,
            "halt_reason": self.reason,
            "timestamp_utc": self.timestamp_utc,
            "halt_source": self.source,
            "severity": self.severity.value,
            "matched_field": self.matched_field,
            "timestamp_valid": self.timestamp_valid,
        }


@dataclass(frozen=True)
class HaltAssessment:
    """The canonical answer to 'is trading halted, why, since when'."""

    halt_active: bool
    halt_kind: HaltKind
    halt_age: HaltAge
    halt_reason: str
    halt_timestamp_utc: str
    halt_operational_day: str
    current_operational_day: str
    halt_source: str
    severity: Severity
    evidence_quality: EvidenceQuality
    halt_event_count: int
    malformed_event_count: int
    daily_reset_occurred: bool
    records: Sequence[HaltRecord] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "halt_active": self.halt_active,
            "halt_kind": self.halt_kind.value,
            "halt_age": self.halt_age.value,
            "halt_reason": self.halt_reason,
            "halt_timestamp_utc": self.halt_timestamp_utc,
            "halt_operational_day": self.halt_operational_day,
            "current_operational_day": self.current_operational_day,
            "halt_source": self.halt_source,
            "severity": self.severity.value,
            "evidence_quality": self.evidence_quality.value,
            "halt_event_count": self.halt_event_count,
            "malformed_event_count": self.malformed_event_count,
            "daily_reset_occurred": self.daily_reset_occurred,
        }
        return SafetyEnvelope().seal(payload)


def detect_halt(
    dataset: Mapping[str, Any] | None = None,
    *,
    events: Iterable[Mapping[str, Any]] | None = None,
    operational_state: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    clock: Clock | None = None,
    daily_drawdown_limit: float = DEFAULT_DAILY_DRAWDOWN_LIMIT,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
) -> HaltAssessment:
    """Assess halt state from every evidence source at once.

    `dataset` is the shape produced by `dry_run_loader.load_dry_run_dataset`
    (SQLite events concatenated with JSONL events, plus alerts and
    operational_state). Extra sources can be passed explicitly.
    """

    resolved_clock = resolve_clock(clock)
    today = resolved_clock.current_operational_day()

    candidates = list(events) if events is not None else []
    if dataset:
        for key in ("events", "alerts", "operational_state"):
            value = dataset.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, Mapping))

    records = [record for record in (_record_from(item) for item in candidates) if record is not None]
    records.extend(_state_records(operational_state, dataset))
    records.extend(_threshold_records(metrics, dataset, limit=daily_drawdown_limit, clock=resolved_clock))

    malformed = [record for record in records if not record.timestamp_valid]
    dated = [record for record in records if record.timestamp_valid]

    if not records:
        return _empty_assessment(today, EvidenceQuality.EMPTY)
    if not dated:
        # Halt evidence exists but nothing carries a usable timestamp. Fail closed:
        # an undatable halt is treated as active, never as an expired one.
        latest = _highest_precedence(malformed)
        return HaltAssessment(
            halt_active=True,
            halt_kind=latest.kind,
            halt_age=HaltAge.MALFORMED,
            halt_reason=latest.reason,
            halt_timestamp_utc="",
            halt_operational_day="",
            current_operational_day=today.isoformat(),
            halt_source=latest.source,
            severity=latest.severity,
            evidence_quality=EvidenceQuality.MALFORMED,
            halt_event_count=len(records),
            malformed_event_count=len(malformed),
            daily_reset_occurred=False,
            records=tuple(records),
        )

    latest = _latest_record(dated)
    latest_day = _parse_ts(latest.timestamp_utc).date()
    if latest_day >= today:
        age = HaltAge.ACTIVE
    elif (today - latest_day) > timedelta(days=stale_after_days):
        age = HaltAge.STALE
    else:
        age = HaltAge.HISTORICAL
    quality = EvidenceQuality.PARTIAL if malformed else EvidenceQuality.OK
    return HaltAssessment(
        halt_active=age is HaltAge.ACTIVE,
        halt_kind=latest.kind,
        halt_age=age,
        halt_reason=latest.reason,
        halt_timestamp_utc=latest.timestamp_utc,
        halt_operational_day=latest_day.isoformat(),
        current_operational_day=today.isoformat(),
        halt_source=latest.source,
        severity=latest.severity,
        evidence_quality=quality,
        halt_event_count=len(records),
        malformed_event_count=len(malformed),
        daily_reset_occurred=latest_day < today,
        records=tuple(records),
    )


def is_halt_event(event: Mapping[str, Any]) -> bool:
    """Whether a single record is halt evidence. The one replacement for the 22 rules."""

    return _record_from(event) is not None


def halt_kind_of(event: Mapping[str, Any]) -> HaltKind:
    """The canonical halt kind for a single record, or HaltKind.NONE."""

    record = _record_from(event)
    return record.kind if record is not None else HaltKind.NONE


def classify_halt_reason(text: str) -> HaltKind:
    """Map a reason string to its canonical halt kind."""

    upper = str(text or "").upper()
    for token, kind in HALT_TOKENS:
        if token in upper:
            return kind
    return HaltKind.NONE


# --------------------------------------------------------------------------- internals


def _record_from(event: Mapping[str, Any]) -> HaltRecord | None:
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    for field_name in SCANNED_FIELDS:
        for container in (event, payload):
            value = container.get(field_name)
            kind = classify_halt_reason(value) if value not in (None, "") else HaltKind.NONE
            if kind is not HaltKind.NONE:
                return _build(event, payload, kind=kind, matched_field=field_name, matched_value=str(value))
    for field_name in STATE_VALUE_FIELDS:
        for container in (event, payload):
            value = container.get(field_name)
            kind = classify_halt_reason(value) if value not in (None, "") else HaltKind.NONE
            if kind is not HaltKind.NONE:
                return _build(event, payload, kind=kind, matched_field=field_name, matched_value=str(value))
    if _truthy(event.get("shadow_paused")) or _truthy(payload.get("shadow_paused")):
        return _build(event, payload, kind=HaltKind.MANUAL, matched_field="shadow_paused", matched_value="shadow_paused")
    return None


def _build(event: Mapping[str, Any], payload: Mapping[str, Any], *, kind: HaltKind, matched_field: str, matched_value: str) -> HaltRecord:
    if kind is HaltKind.UNKNOWN:
        # PAPER_SHADOW_HALTED is a wrapper: resolve the real cause when the record carries one.
        for candidate in (payload.get("halt_reason"), event.get("halt_reason"), payload.get("alert_code"), event.get("alert_code"), payload.get("error")):
            resolved = classify_halt_reason(candidate) if candidate not in (None, "") else HaltKind.NONE
            if resolved not in (HaltKind.NONE, HaltKind.UNKNOWN):
                kind = resolved
                matched_value = str(candidate)
                break
    timestamp = _timestamp_of(event, payload)
    parsed = _parse_ts(timestamp)
    reason = str(payload.get("halt_reason") or event.get("halt_reason") or payload.get("alert_code") or event.get("alert_code") or matched_value or "")
    return HaltRecord(
        kind=kind,
        reason=reason,
        timestamp_utc=parsed.isoformat() if parsed else str(timestamp or ""),
        source=str(event.get("source") or event.get("table") or "unknown"),
        severity=HALT_SEVERITY.get(kind, Severity.WARNING),
        matched_field=matched_field,
        timestamp_valid=parsed is not None,
    )


def _state_records(operational_state: Mapping[str, Any] | None, dataset: Mapping[str, Any] | None) -> list[HaltRecord]:
    state = operational_state
    if state is None and dataset:
        candidate = dataset.get("operational_state")
        state = candidate if isinstance(candidate, Mapping) else None
    if not isinstance(state, Mapping):
        return []
    record = _record_from({**state, "source": str(state.get("source") or "operational_state")})
    return [record] if record is not None else []


def _threshold_records(
    metrics: Mapping[str, Any] | None,
    dataset: Mapping[str, Any] | None,
    *,
    limit: float,
    clock: Clock,
) -> list[HaltRecord]:
    """The threshold rule four legacy modules hardcoded as `<= -3.0`."""

    source = metrics if isinstance(metrics, Mapping) else (dataset.get("metrics") if dataset and isinstance(dataset.get("metrics"), Mapping) else None)
    if not isinstance(source, Mapping):
        return []
    for key in ("daily_drawdown_shadow", "drawdown_paper", "paper_drawdown", "daily_drawdown"):
        if key in source:
            value = _float(source.get(key))
            if value is not None and value <= limit:
                timestamp = str(source.get("timestamp_utc") or clock.now_utc().isoformat())
                return [
                    HaltRecord(
                        kind=HaltKind.DAILY_DRAWDOWN,
                        reason="PAPER_DAILY_DRAWDOWN_HALT",
                        timestamp_utc=timestamp,
                        source="metrics",
                        severity=Severity.CRITICAL,
                        matched_field=key,
                        timestamp_valid=_parse_ts(timestamp) is not None,
                    )
                ]
            break
    return []


def _latest_record(records: Sequence[HaltRecord]) -> HaltRecord:
    """Newest by timestamp; ties broken by halt precedence, never by list position."""

    newest = max(_parse_ts(record.timestamp_utc) for record in records)
    tied = [record for record in records if _parse_ts(record.timestamp_utc) == newest]
    return _highest_precedence(tied)


def _highest_precedence(records: Sequence[HaltRecord]) -> HaltRecord:
    return min(records, key=lambda record: HALT_PRECEDENCE.index(record.kind))


def _empty_assessment(today: date, quality: EvidenceQuality) -> HaltAssessment:
    return HaltAssessment(
        halt_active=False,
        halt_kind=HaltKind.NONE,
        halt_age=HaltAge.NONE,
        halt_reason="",
        halt_timestamp_utc="",
        halt_operational_day="",
        current_operational_day=today.isoformat(),
        halt_source="",
        severity=Severity.NONE,
        evidence_quality=quality,
        halt_event_count=0,
        malformed_event_count=0,
        daily_reset_occurred=False,
        records=(),
    )


def _timestamp_of(event: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    for key in ("timestamp_utc", "created_at_utc", "updated_at_utc", "paused_at_utc", "closed_at_utc", "opened_at_utc"):
        value = event.get(key) or payload.get(key)
        if value:
            return str(value)
    return ""


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
