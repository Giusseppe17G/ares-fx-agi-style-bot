"""Safe UTC datetime parsing helpers for operational reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SafeDatetimeResult:
    value: datetime | None
    status: str
    warning: str
    raw_value: Any
    field_name: str
    source: str


def detect_redacted_datetime(value: Any) -> bool:
    return "[REDACTED" in str(value or "").upper()


def normalize_datetime_string(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return text


def safe_parse_datetime(value: Any, field_name: str | None = None, source: str | None = None, strict: bool = False) -> SafeDatetimeResult:
    field = field_name or ""
    src = source or ""
    if value is None or str(value).strip() == "":
        if strict:
            raise ValueError(f"{field or 'datetime'} is empty")
        return SafeDatetimeResult(None, "MISSING", "DATETIME_MISSING", value, field, src)
    if detect_redacted_datetime(value):
        if strict:
            raise ValueError(f"{field or 'datetime'} is redacted or invalid")
        return SafeDatetimeResult(None, "INVALID", "DATETIME_REDACTED_OR_INVALID", value, field, src)
    try:
        parsed = pd.to_datetime(normalize_datetime_string(value), utc=True, errors="raise")
        if pd.isna(parsed):
            raise ValueError("parsed datetime is NaT")
        dt = parsed.to_pydatetime()
        return SafeDatetimeResult(dt.astimezone(timezone.utc), "OK", "", value, field, src)
    except Exception as exc:
        if strict:
            raise
        return SafeDatetimeResult(None, "INVALID", f"DATETIME_PARSE_FAILED:{exc}", value, field, src)


def safe_to_datetime_series(series: Any, field_name: str | None = None, source: str | None = None) -> tuple[pd.Series, dict[str, Any]]:
    values = list(series) if series is not None else []
    parsed: list[datetime | None] = []
    invalid: list[dict[str, Any]] = []
    for index, item in enumerate(values):
        result = safe_parse_datetime(item, field_name=field_name, source=source)
        parsed.append(result.value)
        if result.status != "OK":
            invalid.append({"index": index, "field_name": result.field_name, "source": result.source, "raw_value": str(result.raw_value), "warning": result.warning})
    return pd.Series(parsed, dtype="object"), {
        "status": "OK" if not invalid else "PARTIAL_INVALID_TIMESTAMPS",
        "invalid_timestamp_count": len(invalid),
        "invalid_timestamp_examples": invalid[:5],
    }
