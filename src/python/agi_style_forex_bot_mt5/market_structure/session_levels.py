"""Session range levels from intraday candles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SessionLevels:
    previous_day_high: float | None
    previous_day_low: float | None
    asian_high: float | None
    asian_low: float | None
    london_high: float | None
    london_low: float | None
    ny_high: float | None
    ny_low: float | None
    current_session: str
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_session_levels(frame: pd.DataFrame) -> SessionLevels:
    if frame.empty or not {"time", "high", "low"}.issubset(frame.columns):
        return SessionLevels(None, None, None, None, None, None, None, None, "UNKNOWN", False)
    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["time"], utc=True)
    data["hour"] = data["timestamp"].dt.hour
    data["date"] = data["timestamp"].dt.date
    latest_date = data["date"].iloc[-1]
    previous = data[data["date"] < latest_date]
    today = data[data["date"] == latest_date]
    latest_hour = int(data["hour"].iloc[-1])
    return SessionLevels(
        _max_or_none(previous, "high"),
        _min_or_none(previous, "low"),
        _max_or_none(today[today["hour"].between(0, 6)], "high"),
        _min_or_none(today[today["hour"].between(0, 6)], "low"),
        _max_or_none(today[today["hour"].between(7, 11)], "high"),
        _min_or_none(today[today["hour"].between(7, 11)], "low"),
        _max_or_none(today[today["hour"].between(13, 20)], "high"),
        _min_or_none(today[today["hour"].between(13, 20)], "low"),
        _session_name(latest_hour),
        False,
    )


def _max_or_none(frame: pd.DataFrame, column: str) -> float | None:
    return None if frame.empty else float(frame[column].astype(float).max())


def _min_or_none(frame: pd.DataFrame, column: str) -> float | None:
    return None if frame.empty else float(frame[column].astype(float).min())


def _session_name(hour: int) -> str:
    if 0 <= hour <= 6:
        return "ASIA"
    if 7 <= hour <= 11:
        return "LONDON"
    if 12 <= hour <= 16:
        return "LONDON_NY_OVERLAP"
    if 17 <= hour <= 20:
        return "NEW_YORK"
    return "ROLLOVER"

