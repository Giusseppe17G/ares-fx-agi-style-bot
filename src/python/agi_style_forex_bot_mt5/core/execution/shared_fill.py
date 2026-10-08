"""One execution model for backtest and paper trading.

The backtester priced fills with its own `_apply_entry_cost`/`_apply_exit_cost`
arithmetic while forward-shadow used `execution_simulation.FillModel` through
`PaperFillModel`. Both adapters now share executable tick-grid alignment,
spread, slippage and commission assumptions. Coarse ticks and fractional
slippage are rounded adversely, so older optimistic results must be rerun.

Backtests replay stored bars, so the live freshness gate is neutralised with an
explicit `tick_age_seconds=0.0`: a replayed bar is not a stale tick. That is the
only difference in how the two callers drive the same model, and it is stated
here rather than hidden in a default.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from ...contracts import MarketSnapshot
from ...execution_simulation import CommissionModel, FillModel, FillResult, SlippageModel
from ..operational_state.errors import ExecutionSimulationError


REPLAY_CONTEXT: dict[str, Any] = {"tick_age_seconds": 0.0}


@dataclass(frozen=True)
class SharedFillModel:
    """The execution assumptions both pipelines share."""

    max_spread_points: float = 25.0
    slippage_points: float = 1.0
    commission_per_lot_round_turn: float = 0.0

    def __post_init__(self) -> None:
        for name in ("max_spread_points", "slippage_points", "commission_per_lot_round_turn"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")

    def simulator(self) -> FillModel:
        return FillModel(
            max_spread_points=self.max_spread_points,
            slippage_model=SlippageModel(fixed_points=self.slippage_points),
            commission_model=CommissionModel(round_turn_per_lot=self.commission_per_lot_round_turn),
        )

    def entry(self, *, direction: str, snapshot: MarketSnapshot, lot: float = 0.0, replay: bool = False, context: Mapping[str, Any] | None = None) -> FillResult:
        return self.simulator().market_entry(direction=direction, snapshot=snapshot, lot=lot, context=self._context(replay, context))

    def exit(self, *, direction: str, snapshot: MarketSnapshot, lot: float = 0.0, base_price: float | None = None, replay: bool = False, context: Mapping[str, Any] | None = None) -> FillResult:
        return self.simulator().market_exit(direction=direction, snapshot=snapshot, lot=lot, base_price=base_price, context=self._context(replay, context))

    def entry_price(self, *, direction: str, snapshot: MarketSnapshot, replay: bool = False) -> float:
        return _price_or_raise(self.entry(direction=direction, snapshot=snapshot, replay=replay), stage="entry")

    def exit_price(self, *, direction: str, snapshot: MarketSnapshot, base_price: float | None = None, replay: bool = False) -> float:
        return _price_or_raise(self.exit(direction=direction, snapshot=snapshot, base_price=base_price, replay=replay), stage="exit")

    def commission(self, lot: float) -> float:
        return max(0.0, self.commission_per_lot_round_turn * lot)

    def _context(self, replay: bool, context: Mapping[str, Any] | None) -> dict[str, Any]:
        merged = dict(REPLAY_CONTEXT) if replay else {}
        merged.update(dict(context or {}))
        return merged

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_spread_points": self.max_spread_points,
            "slippage_points": self.slippage_points,
            "commission_per_lot_round_turn": self.commission_per_lot_round_turn,
        }


def _price_or_raise(result: FillResult, *, stage: str) -> float:
    if not result.accepted or result.fill_price is None:
        raise ExecutionSimulationError(
            f"{stage} fill rejected: {result.reject_reason or result.reject_code}",
            source="shared_fill_model",
            detail={"reject_code": result.reject_code, "stage": stage},
        )
    return float(result.fill_price)
