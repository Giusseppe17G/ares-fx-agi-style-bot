"""Forex session helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def classify_session(timestamp_utc: datetime) -> str:
    if timestamp_utc.tzinfo is None:
        timestamp_utc = timestamp_utc.replace(tzinfo=timezone.utc)
    timestamp_utc = timestamp_utc.astimezone(timezone.utc)
    if timestamp_utc.weekday() == 5 or (timestamp_utc.weekday() == 6 and timestamp_utc.hour < 22):
        return "WEEKEND_CLOSED"
    hour = timestamp_utc.hour
    if 21 <= hour or hour < 1:
        return "ROLLOVER"
    if 0 <= hour < 7:
        return "ASIA"
    if 7 <= hour < 13:
        return "LONDON"
    if 13 <= hour < 16:
        return "LONDON_NY_OVERLAP"
    if 16 <= hour < 21:
        return "NEW_YORK"
    return "UNKNOWN"

