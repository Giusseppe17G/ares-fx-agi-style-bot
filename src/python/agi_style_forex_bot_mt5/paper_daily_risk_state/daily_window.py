"""Operational day helpers for paper risk state."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


def operational_day(value: Any, profile_config: str | Path | None = None) -> str:
    """Return the paper operational day. Defaults to UTC date."""

    parsed = safe_parse_datetime(value, field_name="timestamp_utc", source="paper_daily_risk")
    if parsed.value is None:
        return ""
    return parsed.value.astimezone(timezone.utc).date().isoformat()


def current_operational_day(now: datetime | None = None, profile_config: str | Path | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
