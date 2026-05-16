"""Health state contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agi_style_forex_bot_mt5.contracts import utc_now


@dataclass(frozen=True)
class HealthState:
    mode: str
    mt5_connected: bool
    last_heartbeat_utc: str | None
    shadow_paused: bool
    open_paper_trades: int
    critical_errors_recent: int
    sqlite_status: str
    jsonl_status: str
    telegram_status: str
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_health_state() -> HealthState:
    return HealthState(
        mode="unknown",
        mt5_connected=False,
        last_heartbeat_utc=utc_now().isoformat(),
        shadow_paused=False,
        open_paper_trades=0,
        critical_errors_recent=0,
        sqlite_status="UNKNOWN",
        jsonl_status="UNKNOWN",
        telegram_status="UNKNOWN",
        execution_attempted=False,
    )

