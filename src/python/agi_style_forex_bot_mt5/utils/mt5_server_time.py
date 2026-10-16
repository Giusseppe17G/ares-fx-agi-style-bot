"""Declared MT5 trade-server clock convention (``MT5_SERVER_TIME``).

The MetaTrader5 Python package returns tick and bar times as epoch seconds of
the trade server's wall clock. Many brokers run that clock at UTC+2 in winter
and UTC+3 while New York observes daylight saving time ("New York close":
server midnight is 17:00 in New York). The operator declares the convention
from the broker's documentation; nothing is inferred from a tick. Times are
converted once, where they are read, and every later freshness, closed-bar and
session check works in UTC. A server time that falls in a daylight-saving gap
or overlap cannot be converted and is rejected (fail closed).

Conventions:

- ``UTC`` (default): times are already UTC; no conversion.
- ``NY_CLOSE``: UTC+3 while the United States observes DST, UTC+2 otherwise.
  The US rule in force since 2007 is applied (second Sunday of March 07:00 UTC
  to first Sunday of November 06:00 UTC); earlier times are rejected.
- ``EET``: UTC+3 during European summer time, UTC+2 otherwise (last Sunday of
  March 01:00 UTC to last Sunday of October 01:00 UTC; from 1996).
- ``UTC+HH:MM`` / ``UTC-HH:MM``: a fixed offset, at most 14 hours.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

import pandas as pd

UTC_CONVENTION = "UTC"
NY_CLOSE = "NY_CLOSE"
EET = "EET"
_FIXED = re.compile(r"^UTC([+-])(\d{2}):(\d{2})$")
_US_RULE_FIRST_YEAR = 2007
_EU_RULE_FIRST_YEAR = 1996


def parse_server_time(value: Any) -> str:
    """Return the canonical convention name or raise ``ValueError``."""

    text = str(value if value is not None else "").strip().upper()
    if text in {UTC_CONVENTION, NY_CLOSE, EET}:
        return text
    match = _FIXED.match(text)
    if match:
        hours, minutes = int(match.group(2)), int(match.group(3))
        if minutes < 60 and hours * 60 + minutes <= 14 * 60:
            return "UTC+00:00" if hours == minutes == 0 else text
    raise ValueError("MT5_SERVER_TIME must be UTC, NY_CLOSE, EET or UTC+HH:MM / UTC-HH:MM (max 14 h)")


def _fixed_offset_seconds(convention: str) -> int | None:
    if convention == UTC_CONVENTION:
        return 0
    match = _FIXED.match(convention)
    if not match:
        return None
    sign = 1 if match.group(1) == "+" else -1
    return sign * (int(match.group(2)) * 3600 + int(match.group(3)) * 60)


def _nth_sunday(year: int, month: int, nth: int) -> datetime:
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    days_to_sunday = (6 - first.weekday()) % 7
    return first + timedelta(days=days_to_sunday + 7 * (nth - 1))


def us_dst_bounds_utc(year: int) -> tuple[datetime, datetime]:
    """US DST start/end instants in UTC (rule in force since 2007)."""

    if year < _US_RULE_FIRST_YEAR:
        raise ValueError("NY_CLOSE server time is only defined from 2007")
    start = _nth_sunday(year, 3, 2) + timedelta(hours=7)   # 02:00 EST
    end = _nth_sunday(year, 11, 1) + timedelta(hours=6)    # 02:00 EDT
    return start, end


def _last_sunday(year: int, month: int) -> datetime:
    following = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
    last = following - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def eu_dst_bounds_utc(year: int) -> tuple[datetime, datetime]:
    """European summer time start/end instants in UTC (rule in force since 1996)."""

    if year < _EU_RULE_FIRST_YEAR:
        raise ValueError("EET server time is only defined from 1996")
    return _last_sunday(year, 3) + timedelta(hours=1), _last_sunday(year, 10) + timedelta(hours=1)


_DST_BOUNDS = {NY_CLOSE: us_dst_bounds_utc, EET: eu_dst_bounds_utc}


def _summer(convention: str, instant_utc: datetime) -> bool:
    start, end = _DST_BOUNDS[convention](instant_utc.year)
    return start <= instant_utc < end


def server_offset_seconds(convention: str, instant_utc: datetime) -> int:
    """Offset of the server clock from UTC at a UTC instant."""

    convention = parse_server_time(convention)
    fixed = _fixed_offset_seconds(convention)
    if fixed is not None:
        return fixed
    return 10800 if _summer(convention, instant_utc.astimezone(timezone.utc)) else 7200


def server_wall_to_utc(server_wall: datetime, convention: str) -> datetime | None:
    """Convert a server wall time (carried as a UTC datetime) to true UTC.

    Returns None for a time in a daylight-saving gap or overlap, or outside the
    supported range; callers treat that as an invalid timestamp.
    """

    convention = parse_server_time(convention)
    wall = server_wall.astimezone(timezone.utc)
    fixed = _fixed_offset_seconds(convention)
    if fixed is not None:
        return wall - timedelta(seconds=fixed)
    try:
        candidates = [wall - timedelta(seconds=offset) for offset in (10800, 7200)
                      if server_offset_seconds(convention, wall - timedelta(seconds=offset)) == offset]
    except ValueError:
        return None
    return candidates[0] if len(candidates) == 1 else None


def utc_to_server_wall(instant_utc: datetime, convention: str) -> datetime:
    """Express a UTC instant as server wall time (for MT5 range queries)."""

    instant = instant_utc.astimezone(timezone.utc)
    return instant + timedelta(seconds=server_offset_seconds(convention, instant))


def server_series_to_utc(values: pd.Series, convention: str) -> pd.Series:
    """Vectorised ``server_wall_to_utc`` for tz-aware UTC timestamps.

    Raises ``ValueError`` if any value cannot be converted unambiguously.
    """

    convention = parse_server_time(convention)
    fixed = _fixed_offset_seconds(convention)
    if fixed is not None:
        return values - pd.Timedelta(seconds=fixed) if fixed else values
    summer = values - pd.Timedelta(hours=3)
    winter = values - pd.Timedelta(hours=2)
    summer_ok = _summer_series(convention, summer)
    winter_ok = ~_summer_series(convention, winter)
    if bool((summer_ok == winter_ok).any()):
        raise ValueError("server time falls in a daylight-saving gap or overlap")
    return summer.where(summer_ok, winter)


def _summer_series(convention: str, values: pd.Series) -> pd.Series:
    years = values.dt.year
    rule = _DST_BOUNDS[convention]
    bounds = {int(year): rule(int(year)) for year in years.unique()}  # raises for years before the rule
    starts = pd.to_datetime(years.map(lambda year: bounds[int(year)][0]), utc=True)
    ends = pd.to_datetime(years.map(lambda year: bounds[int(year)][1]), utc=True)
    return (values >= starts) & (values < ends)
