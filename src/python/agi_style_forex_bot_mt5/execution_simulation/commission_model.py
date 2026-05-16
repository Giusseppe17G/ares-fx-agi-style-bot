"""Commission cost assumptions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CommissionEstimate:
    commission: float
    model: str
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CommissionModel:
    """Support zero, per-side and round-turn commission assumptions."""

    def __init__(self, *, round_turn_per_lot: float = 0.0, per_side_per_lot: float | None = None, profile: Mapping[str, Any] | None = None) -> None:
        self.round_turn_per_lot = max(0.0, round_turn_per_lot)
        self.per_side_per_lot = per_side_per_lot
        self.profile = dict(profile or {})

    def estimate(self, *, lot: float, symbol: str = "") -> CommissionEstimate:
        symbol_profile = self._profile_for(symbol)
        if "commission_per_lot_round_turn" in symbol_profile:
            cost = float(symbol_profile["commission_per_lot_round_turn"]) * lot
            return CommissionEstimate(max(0.0, cost), "profile_round_turn", False)
        if self.per_side_per_lot is not None:
            return CommissionEstimate(max(0.0, self.per_side_per_lot * 2.0 * lot), "per_side", False)
        return CommissionEstimate(max(0.0, self.round_turn_per_lot * lot), "round_turn", False)

    def _profile_for(self, symbol: str) -> dict[str, Any]:
        symbols = self.profile.get("symbols")
        if isinstance(symbols, Mapping):
            return dict(symbols.get(symbol.upper()) or {})
        return {}

