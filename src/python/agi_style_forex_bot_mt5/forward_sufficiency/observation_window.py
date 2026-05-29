"""Observation window helpers for forward sufficiency audits."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


def calculate_observation_window(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return first/last valid UTC timestamps and observed hours."""

    timestamps: list[datetime] = []
    invalid_count = 0
    for item in items:
        for field in ("timestamp_utc", "opened_at_utc", "closed_at_utc", "entry_time_utc", "exit_time_utc"):
            if field not in item or item.get(field) in (None, ""):
                continue
            parsed = safe_parse_datetime(item.get(field), field_name=field, source=str(item.get("source", "forward_sufficiency")))
            if parsed.value is None:
                invalid_count += 1
            else:
                timestamps.append(parsed.value.astimezone(timezone.utc))
    if not timestamps:
        return {
            "observation_start_utc": None,
            "observation_end_utc": None,
            "hours_observed": 0.0,
            "invalid_timestamp_count": invalid_count,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    start = min(timestamps)
    end = max(timestamps)
    hours = max((end - start).total_seconds() / 3600.0, 0.0)
    return {
        "observation_start_utc": start.isoformat(),
        "observation_end_utc": end.isoformat(),
        "hours_observed": round(hours, 4),
        "invalid_timestamp_count": invalid_count,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
