"""Conservative paper fill model using real bid/ask snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from agi_style_forex_bot_mt5.contracts import MarketSnapshot
from agi_style_forex_bot_mt5.execution_simulation import CommissionModel, FillModel, SlippageModel


@dataclass(frozen=True)
class PaperFillModel:
    max_spread_points: float = 25.0
    slippage_points: float = 1.0
    commission_per_lot_round_turn: float = 0.0

    def simulator(self) -> FillModel:
        return FillModel(
            max_spread_points=self.max_spread_points,
            slippage_model=SlippageModel(fixed_points=self.slippage_points),
            commission_model=CommissionModel(round_turn_per_lot=self.commission_per_lot_round_turn),
        )

    def validate_spread(self, snapshot: MarketSnapshot) -> None:
        if snapshot.spread_points > self.max_spread_points:
            raise ValueError("paper fill rejected: spread exceeds maximum")

    def entry_price(self, *, direction: str, snapshot: MarketSnapshot) -> float:
        result = self.simulator().market_entry(direction=direction, snapshot=snapshot)
        if not result.accepted or result.fill_price is None:
            raise ValueError(f"paper fill rejected: {result.reject_reason or result.reject_code}")
        return result.fill_price

    def exit_price(self, *, direction: str, snapshot: MarketSnapshot, base_price: float | None = None) -> float:
        result = self.simulator().market_exit(direction=direction, snapshot=snapshot, base_price=base_price)
        if not result.accepted or result.fill_price is None:
            raise ValueError(f"paper fill rejected: {result.reject_reason or result.reject_code}")
        return result.fill_price

    def entry_result(self, *, direction: str, snapshot: MarketSnapshot, lot: float = 0.0):
        return self.simulator().market_entry(direction=direction, snapshot=snapshot, lot=lot)

    def exit_result(self, *, direction: str, snapshot: MarketSnapshot, lot: float = 0.0, base_price: float | None = None):
        return self.simulator().market_exit(direction=direction, snapshot=snapshot, lot=lot, base_price=base_price)

    def commission(self, lot: float) -> float:
        return max(0.0, self.commission_per_lot_round_turn * lot)
