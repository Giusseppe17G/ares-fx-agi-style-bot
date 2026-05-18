"""MT5 broker/server time normalization helpers.

The MetaTrader5 Python API may expose tick timestamps in broker server time
instead of true UTC.  This module normalizes only well-known, fresh-looking
future offsets and keeps all ambiguous cases fail-closed.
"""

from __future__ import annotations

import json
import os
import platform
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_KNOWN_OFFSETS_SECONDS: tuple[int, ...] = (-10800, -7200, -3600, 0, 3600, 7200, 10800)
DEFAULT_MAX_TICK_AGE_SECONDS = 5
DEFAULT_MAX_FUTURE_OFFSET_SECONDS = 21600
OFFSET_MATCH_TOLERANCE_SECONDS = 120


def normalize_tick_time(
    raw_tick_time: Any,
    raw_tick_time_msc: Any,
    now_utc: datetime,
    config: Any | None = None,
) -> dict[str, Any]:
    """Normalize an MT5 tick timestamp and return JSON-safe diagnostics."""

    now = _as_utc(now_utc)
    max_age = int(getattr(config, "max_tick_age_seconds", DEFAULT_MAX_TICK_AGE_SECONDS))
    max_future = int(getattr(config, "max_future_tick_offset_seconds", DEFAULT_MAX_FUTURE_OFFSET_SECONDS))
    normalize_enabled = bool(getattr(config, "normalize_broker_time", True))
    detection_enabled = bool(getattr(config, "broker_time_offset_detection", True))
    known_offsets = tuple(
        int(value)
        for value in getattr(config, "known_broker_time_offsets_seconds", DEFAULT_KNOWN_OFFSETS_SECONDS)
    )

    time_utc = _unix_timestamp(raw_tick_time, divisor=1.0)
    time_msc_utc = _unix_timestamp(raw_tick_time_msc, divisor=1000.0)
    selected_raw = time_msc_utc or time_utc
    selected_source = "time_msc" if time_msc_utc is not None else ("time" if time_utc is not None else "none")

    raw_age = (now - selected_raw).total_seconds() if selected_raw is not None else None
    age_from_time = (now - time_utc).total_seconds() if time_utc is not None else None
    age_from_time_msc = (now - time_msc_utc).total_seconds() if time_msc_utc is not None else None

    normalized = selected_raw
    offset = 0
    timestamp_normalized = False
    reason = "raw tick timestamp accepted"
    status = "FRESH"
    reject_code = None
    reject_reason = None

    if selected_raw is None or raw_age is None:
        status = "INVALID_TIMESTAMP"
        normalized = None
        reason = "tick timestamp is unavailable or invalid"
        reject_code = "MARKET_DATA_INVALID"
        reject_reason = reason
    elif raw_age < -max_future:
        status = "FUTURE_TOO_FAR"
        reason = "tick timestamp is too far in the future"
        reject_code = "MARKET_DATA_INVALID"
        reject_reason = reason
    elif abs(raw_age) <= max_age:
        status = "FRESH"
        reason = "raw tick timestamp is fresh"
    elif raw_age < -max_age:
        detected = (
            detect_broker_time_offset(selected_raw, now, known_offsets)
            if normalize_enabled and detection_enabled
            else None
        )
        if detected is None:
            status = "FUTURE_TOO_FAR"
            reason = "future tick offset is not in known broker offsets"
            reject_code = "MARKET_DATA_INVALID"
            reject_reason = reason
        else:
            offset = int(detected)
            normalized = selected_raw.timestamp() - offset
            normalized_dt = datetime.fromtimestamp(normalized, timezone.utc)
            normalized_age = (now - normalized_dt).total_seconds()
            timestamp_normalized = True
            if abs(normalized_age) <= max_age:
                status = "NORMALIZED_FRESH"
                reason = f"broker server time offset normalized by {offset} seconds"
                normalized = normalized_dt
            else:
                status = "NORMALIZED_STALE"
                reason = "tick timestamp remains stale after broker offset normalization"
                reject_code = "MARKET_DATA_INVALID"
                reject_reason = reason
                normalized = normalized_dt
    else:
        status = "STALE"
        reason = "tick timestamp is stale"
        reject_code = "MARKET_DATA_INVALID"
        reject_reason = reason

    normalized_dt = normalized if isinstance(normalized, datetime) else None
    normalized_age = (now - normalized_dt).total_seconds() if normalized_dt is not None else None
    return {
        "tick_time_raw": raw_tick_time,
        "tick_time_msc_raw": raw_tick_time_msc,
        "tick_time_utc_raw": _iso(selected_raw),
        "tick_time_utc": _iso(time_utc),
        "tick_time_msc_utc": _iso(time_msc_utc),
        "normalized_tick_utc": _iso(normalized_dt),
        "selected_tick_time_source": selected_source,
        "selected_tick_time_utc": _iso(normalized_dt),
        "timestamp_normalized": timestamp_normalized,
        "broker_time_offset_seconds": offset if timestamp_normalized else 0,
        "tick_age_seconds_raw": raw_age,
        "tick_age_seconds_normalized": normalized_age,
        "tick_age_seconds": normalized_age,
        "tick_age_seconds_from_time": age_from_time,
        "tick_age_seconds_from_time_msc": age_from_time_msc,
        "tick_time_status": status,
        "normalization_reason": reason,
        "reject_code": reject_code,
        "reject_reason": reject_reason,
        "now_utc": now.isoformat(),
    }


def detect_broker_time_offset(
    raw_tick_dt_utc: datetime,
    now_utc: datetime,
    known_offsets_seconds: Iterable[int] = DEFAULT_KNOWN_OFFSETS_SECONDS,
) -> int | None:
    """Return the nearest known broker offset when the raw tick is ahead."""

    raw = _as_utc(raw_tick_dt_utc)
    now = _as_utc(now_utc)
    raw_delta = (raw - now).total_seconds()
    if raw_delta <= 0:
        return None
    candidates = sorted((int(value) for value in known_offsets_seconds), key=lambda value: abs(raw_delta - value))
    if not candidates:
        return None
    best = candidates[0]
    if best <= 0:
        return None
    return best if abs(raw_delta - best) <= OFFSET_MATCH_TOLERANCE_SECONDS else None


def classify_tick_time(
    raw_tick_dt_utc: datetime | None,
    normalized_tick_dt_utc: datetime | None,
    now_utc: datetime,
    max_tick_age_seconds: int,
    max_future_offset_seconds: int,
) -> str:
    """Classify raw/normalized tick freshness without mutating inputs."""

    now = _as_utc(now_utc)
    if raw_tick_dt_utc is None or normalized_tick_dt_utc is None:
        return "INVALID_TIMESTAMP"
    raw = _as_utc(raw_tick_dt_utc)
    normalized = _as_utc(normalized_tick_dt_utc)
    raw_age = (now - raw).total_seconds()
    normalized_age = (now - normalized).total_seconds()
    if raw_age < -max_future_offset_seconds:
        return "FUTURE_TOO_FAR"
    if abs(raw_age) <= max_tick_age_seconds:
        return "FRESH"
    if abs(normalized_age) <= max_tick_age_seconds:
        return "NORMALIZED_FRESH"
    if normalized_age > max_tick_age_seconds:
        return "NORMALIZED_STALE"
    return "FUTURE_TOO_FAR"


def build_time_diagnostics(
    *,
    raw_tick_time: Any,
    raw_tick_time_msc: Any,
    now_utc: datetime,
    config: Any | None = None,
    mt5_terminal_available: bool | None = None,
) -> dict[str, Any]:
    """Build normalized tick plus host environment diagnostics."""

    return {
        **normalize_tick_time(raw_tick_time, raw_tick_time_msc, now_utc, config=config),
        **build_environment_diagnostics(mt5_terminal_available=mt5_terminal_available),
    }


def build_environment_diagnostics(*, mt5_terminal_available: bool | None = None) -> dict[str, Any]:
    """Return host clock/environment details for MT5 diagnostics."""

    local_now = datetime.now().astimezone()
    utc_now = datetime.now(timezone.utc)
    return {
        "system_local_time": local_now.isoformat(),
        "system_utc_time": utc_now.isoformat(),
        "system_timezone_name": _timezone_name(local_now),
        "python_datetime_now_utc": utc_now.isoformat(),
        "mt5_terminal_available": mt5_terminal_available,
        "environment_name": _environment_name(),
    }


def persist_broker_time_offset(
    *,
    diagnostic: Mapping[str, Any],
    symbol: str,
    source: str,
    runtime_path: str | Path = "data/runtime/broker_time_offset.json",
    account_info: Any | None = None,
) -> str | None:
    """Persist a non-secret broker time offset hint when normalization is valid."""

    if not diagnostic.get("timestamp_normalized"):
        return None
    offset = diagnostic.get("broker_time_offset_seconds")
    try:
        selected_offset = int(offset)
    except (TypeError, ValueError):
        return None
    output = Path(runtime_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    existing: dict[str, Any] = {}
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    offsets_by_symbol = dict(existing.get("offsets_by_symbol") or {})
    offsets_by_symbol[symbol] = {
        "offset_seconds": selected_offset,
        "last_confirmed_utc": now,
        "tick_time_status": diagnostic.get("tick_time_status"),
    }
    payload = {
        "detected_at_utc": existing.get("detected_at_utc") or now,
        "broker": _safe_attr(account_info, "company"),
        "server": _safe_attr(account_info, "server"),
        "account_login": _redact_login(_safe_attr(account_info, "login")),
        "offsets_by_symbol": offsets_by_symbol,
        "selected_offset_seconds": selected_offset,
        "confidence": min(1.0, max(0.0, len(offsets_by_symbol) / 3.0)),
        "source": source,
        "last_confirmed_utc": now,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def _unix_timestamp(raw_value: Any, *, divisor: float) -> datetime | None:
    if raw_value in (None, ""):
        return None
    try:
        value = float(raw_value) / divisor
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value < 946684800 or value > 4102444800:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _timezone_name(local_now: datetime) -> str:
    return str(local_now.tzname() or "")


def _environment_name() -> str:
    system = platform.system().upper()
    if system != "WINDOWS":
        return "UNKNOWN"
    hostname = socket.gethostname().upper()
    if os.getenv("AWS_EXECUTION_ENV") or os.getenv("EC2_INSTANCE_ID") or hostname.startswith("EC2"):
        return "WINDOWS_EC2"
    return "LOCAL_WINDOWS"


def _safe_attr(obj: Any | None, name: str) -> Any:
    if obj is None:
        return None
    return getattr(obj, name, None)


def _redact_login(login: Any) -> str | None:
    if login in (None, ""):
        return None
    text = str(login)
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"
