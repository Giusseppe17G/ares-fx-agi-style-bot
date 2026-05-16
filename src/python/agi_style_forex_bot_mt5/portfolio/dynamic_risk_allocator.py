"""Dynamic risk allocation for shadow/paper trades."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class DynamicRiskDecision:
    risk_multiplier: float
    reasons: tuple[str, ...]
    checks: dict[str, Any]
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DynamicRiskAllocator:
    """Reduce or maintain risk; never exceed 1.0 by default."""

    def allocate(self, context: Mapping[str, Any]) -> DynamicRiskDecision:
        multiplier = 1.0
        reasons: list[str] = []
        drawdown = abs(float(context.get("drawdown_pct") or context.get("drawdown_paper") or 0.0))
        losses = int(context.get("consecutive_losses") or 0)
        spread_ratio = float(context.get("spread_ratio") or 0.0)
        broker_score = float(context.get("broker_readiness_score") or 100.0)
        ml_probability = context.get("ml_probability")
        correlation = abs(float(context.get("correlation") or 0.0))
        watchlist = bool(context.get("symbol_watchlist", False))
        if drawdown >= 3.0:
            multiplier = min(multiplier, 0.5)
            reasons.append("drawdown warning")
        if losses >= 3:
            multiplier = min(multiplier, 0.25)
            reasons.append("loss streak >= 3")
        if spread_ratio >= 1.0 or broker_score < 40:
            multiplier = 0.0
            reasons.append("severe broker degradation")
        elif spread_ratio >= 0.75 or broker_score < 70:
            multiplier = min(multiplier, 0.5)
            reasons.append("broker or spread borderline")
        if ml_probability is not None and float(ml_probability) < 0.60:
            multiplier = min(multiplier, 0.5)
            reasons.append("ML probability borderline")
        if correlation >= 0.85:
            multiplier = min(multiplier, 0.5)
            reasons.append("high correlation")
        if watchlist:
            multiplier = min(multiplier, 0.5)
            reasons.append("symbol watchlist")
        multiplier = max(0.0, min(1.0, multiplier))
        return DynamicRiskDecision(risk_multiplier=multiplier, reasons=tuple(reasons), checks=dict(context), execution_attempted=False)

