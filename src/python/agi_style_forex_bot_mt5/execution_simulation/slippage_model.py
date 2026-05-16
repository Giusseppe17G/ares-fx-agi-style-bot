"""Conservative slippage assumptions for shadow execution simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SlippageEstimate:
    assumed_slippage_points: float
    slippage_reason: str
    confidence: float
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SlippageModel:
    """Estimate adverse slippage from spread, volatility, session and readiness."""

    def __init__(self, *, fixed_points: float = 1.0, stress_multiplier: float = 1.0) -> None:
        self.fixed_points = max(0.0, fixed_points)
        self.stress_multiplier = max(1.0, stress_multiplier)

    def estimate(self, context: Mapping[str, Any]) -> SlippageEstimate:
        spread_percentile = float(context.get("spread_percentile") or 50.0)
        atr_points = float(context.get("atr_points") or 0.0)
        broker_readiness = float(context.get("broker_readiness_score") or 100.0)
        session = str(context.get("session") or "").upper()
        points = self.fixed_points
        reasons = [f"fixed={self.fixed_points}"]
        if spread_percentile >= 95:
            points += 2.0
            reasons.append("spread p95+")
        elif spread_percentile >= 75:
            points += 1.0
            reasons.append("spread elevated")
        if atr_points > 50:
            points += 1.0
            reasons.append("high ATR")
        if session in {"ROLLOVER", "WEEKEND_CLOSED"}:
            points += 3.0
            reasons.append("thin session")
        if broker_readiness < 70:
            points += 1.5
            reasons.append("broker readiness below 70")
        points *= self.stress_multiplier
        confidence = 0.75 if reasons == [f"fixed={self.fixed_points}"] else 0.55
        return SlippageEstimate(round(points, 4), "; ".join(reasons), confidence, False)

