"""Partial fill simulation structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PartialFillDecision:
    status: str
    filled_lot: float
    reject_reason: str = ""
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PartialFillModel:
    """Default to full conservative fills unless liquidity/spread data rejects."""

    def decide(self, *, requested_lot: float, context: Mapping[str, Any] | None = None) -> PartialFillDecision:
        context = dict(context or {})
        if bool(context.get("low_liquidity", False)):
            return PartialFillDecision("REJECTED_LOW_LIQUIDITY", 0.0, "low liquidity", False)
        if bool(context.get("spread_extreme", False)):
            return PartialFillDecision("REJECTED_SPREAD_EXTREME", 0.0, "spread extreme", False)
        return PartialFillDecision("FULL_FILL", requested_lot, "", False)

