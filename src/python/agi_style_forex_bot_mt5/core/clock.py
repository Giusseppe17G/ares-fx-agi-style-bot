"""Injectable clock so time-dependent logic is testable and reproducible."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """The time source every time-dependent component should accept."""

    def now_utc(self) -> datetime: ...

    def now_local(self, tz: tzinfo | None = None) -> datetime: ...

    def current_operational_day(self) -> date: ...


class _BaseClock:
    def now_local(self, tz: tzinfo | None = None) -> datetime:
        return self.now_utc().astimezone(tz) if tz is not None else self.now_utc().astimezone()

    def current_operational_day(self) -> date:
        """The UTC calendar day used by the daily risk/halt lifecycle."""

        return self.now_utc().date()

    def current_operational_day_iso(self) -> str:
        return self.current_operational_day().isoformat()


class SystemClock(_BaseClock):
    """Wall-clock time. The only place `datetime.now` should be called."""

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass
class FrozenClock(_BaseClock):
    """A clock stopped at a fixed instant, optionally advanced by hand."""

    instant: datetime

    def __post_init__(self) -> None:
        if self.instant.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware instant")
        self.instant = self.instant.astimezone(timezone.utc)

    def now_utc(self) -> datetime:
        return self.instant

    def advance(self, delta: timedelta) -> "FrozenClock":
        self.instant = self.instant + delta
        return self


SYSTEM_CLOCK = SystemClock()


def resolve_clock(clock: Clock | None = None) -> Clock:
    """Return the given clock, or the shared system clock."""

    return clock if clock is not None else SYSTEM_CLOCK
