"""Symbol quality contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SymbolQuality:
    canonical_symbol: str
    broker_symbol: str
    symbol_visible: bool
    trade_mode: str
    trade_allowed: bool
    bid: float
    ask: float
    spread_points: float
    point: float
    digits: int
    tick_value: float
    tick_size: float
    trade_contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: int
    freeze_level_points: int
    filling_mode: str
    tick_time_utc: str | None
    tick_age_seconds: float | None
    mt5_last_error: Any
    market_is_probably_closed: bool
    rates_available_m5: bool
    rates_available_m15: bool
    rates_available_h1: bool
    bars_count_m5: int
    bars_count_m15: int
    bars_count_h1: int
    read_latency_ms_tick: int
    read_latency_ms_rates: int
    status: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    readiness_score: float = 0.0
    execution_attempted: bool = False
    order_send_called: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

