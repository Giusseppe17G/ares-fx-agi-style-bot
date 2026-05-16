"""Conservative paper fill model using real bid/ask snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from agi_style_forex_bot_mt5.contracts import MarketSnapshot


@dataclass(frozen=True)
class PaperFillModel:
    max_spread_points: float = 25.0
    slippage_points: float = 1.0
    commission_per_lot_round_turn: float = 0.0

    def validate_spread(self, snapshot: MarketSnapshot) -> None:
        if snapshot.spread_points > self.max_spread_points:
            raise ValueError("paper fill rejected: spread exceeds maximum")

    def entry_price(self, *, direction: str, snapshot: MarketSnapshot) -> float:
        self.validate_spread(snapshot)
        slip = self.slippage_points * snapshot.point
        return (snapshot.ask + slip) if direction.upper() == "BUY" else (snapshot.bid - slip)

    def exit_price(self, *, direction: str, snapshot: MarketSnapshot, base_price: float | None = None) -> float:
        self.validate_spread(snapshot)
        reference = base_price if base_price is not None else (snapshot.bid if direction.upper() == "BUY" else snapshot.ask)
        slip = self.slippage_points * snapshot.point
        return (reference - slip) if direction.upper() == "BUY" else (reference + slip)

    def commission(self, lot: float) -> float:
        return max(0.0, self.commission_per_lot_round_turn * lot)
