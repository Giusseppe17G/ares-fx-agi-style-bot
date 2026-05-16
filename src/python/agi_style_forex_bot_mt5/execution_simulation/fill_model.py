"""Refined fill simulation for shadow/paper execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from agi_style_forex_bot_mt5.contracts import MarketSnapshot

from .commission_model import CommissionModel
from .gap_model import GapModel
from .latency_model import LatencyModel
from .partial_fill_model import PartialFillModel
from .slippage_model import SlippageModel
from .spread_model import SpreadModel

SIMULATION_VERSION = "execution_simulation_v1"


@dataclass(frozen=True)
class FillResult:
    accepted: bool
    fill_price: float | None
    fill_side: str
    fill_quality: str
    reject_code: str = ""
    reject_reason: str = ""
    assumed_slippage_points: float = 0.0
    commission: float = 0.0
    metadata: Mapping[str, Any] | None = None
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = dict(self.metadata or {})
        return data


class FillModel:
    """Simulate market fills with conservative spread, slippage and freshness gates."""

    def __init__(
        self,
        *,
        max_spread_points: float = 25.0,
        max_tick_age_seconds: float = 120.0,
        spread_model: SpreadModel | None = None,
        slippage_model: SlippageModel | None = None,
        commission_model: CommissionModel | None = None,
        latency_model: LatencyModel | None = None,
        partial_fill_model: PartialFillModel | None = None,
        gap_model: GapModel | None = None,
    ) -> None:
        self.max_spread_points = max_spread_points
        self.max_tick_age_seconds = max_tick_age_seconds
        self.spread_model = spread_model or SpreadModel(max_spread_points=max_spread_points)
        self.slippage_model = slippage_model or SlippageModel()
        self.commission_model = commission_model or CommissionModel()
        self.latency_model = latency_model or LatencyModel()
        self.partial_fill_model = partial_fill_model or PartialFillModel()
        self.gap_model = gap_model or GapModel()

    def market_entry(
        self,
        *,
        direction: str,
        snapshot: MarketSnapshot,
        lot: float = 0.0,
        context: Mapping[str, Any] | None = None,
    ) -> FillResult:
        return self._fill(direction=direction, snapshot=snapshot, lot=lot, context=context, is_entry=True)

    def market_exit(
        self,
        *,
        direction: str,
        snapshot: MarketSnapshot,
        lot: float = 0.0,
        base_price: float | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> FillResult:
        return self._fill(direction=direction, snapshot=snapshot, lot=lot, context=context, is_entry=False, base_price=base_price)

    def resolve_bar_exit(self, *, direction: str, open_price: float, high: float, low: float, sl: float, tp: float, mode: str = "conservative") -> dict[str, Any] | None:
        decision = self.gap_model.resolve_bar_exit(direction=direction, open_price=open_price, high=high, low=low, sl=sl, tp=tp, mode=mode)
        return decision.to_dict() if decision else None

    def _fill(
        self,
        *,
        direction: str,
        snapshot: MarketSnapshot,
        lot: float,
        context: Mapping[str, Any] | None,
        is_entry: bool,
        base_price: float | None = None,
    ) -> FillResult:
        context = dict(context or {})
        try:
            snapshot.validate()
        except ValueError as exc:
            return self._reject("SNAPSHOT_INVALID", str(exc), direction, {})
        if bool(context.get("market_closed", False)):
            return self._reject("MARKET_CLOSED", "market appears closed", direction, {})
        tick_age = context.get("tick_age_seconds")
        if tick_age is None:
            tick_age = (datetime.now(timezone.utc) - snapshot.timestamp_utc.astimezone(timezone.utc)).total_seconds()
        if float(tick_age) > self.max_tick_age_seconds:
            return self._reject("TICK_STALE", "tick is stale", direction, {"tick_age_seconds": tick_age})
        spread = self.spread_model.estimate(symbol=snapshot.symbol, snapshot=snapshot, forward_spreads=context.get("forward_spreads", ()))
        if not spread.trade_allowed_by_spread:
            return self._reject("SPREAD_EXTREME", "spread exceeds maximum", direction, {"spread": spread.to_dict()})
        partial = self.partial_fill_model.decide(requested_lot=lot, context={"spread_extreme": spread.spread_regime == "EXTREME", **context})
        if partial.status.startswith("REJECTED"):
            return self._reject(partial.status, partial.reject_reason, direction, {"partial_fill": partial.to_dict(), "spread": spread.to_dict()})
        slippage = self.slippage_model.estimate({**context, "spread_percentile": _spread_percentile(spread, snapshot)})
        commission = self.commission_model.estimate(lot=lot, symbol=snapshot.symbol)
        latency = self.latency_model.estimate(context)
        price = self._base_price(direction=direction, snapshot=snapshot, is_entry=is_entry, base_price=base_price)
        slip_value = slippage.assumed_slippage_points * snapshot.point
        if direction.upper() == "BUY":
            price = price + slip_value if is_entry else price - slip_value
        else:
            price = price - slip_value if is_entry else price + slip_value
        metadata = {
            "execution_simulation_version": SIMULATION_VERSION,
            "spread_model_used": spread.to_dict(),
            "slippage_model_used": slippage.to_dict(),
            "commission_model_used": commission.to_dict(),
            "latency_assumption": latency.to_dict(),
            "partial_fill": partial.to_dict(),
            "ambiguity_flags": tuple(context.get("ambiguity_flags", ())),
        }
        quality = "GOOD" if spread.spread_regime == "NORMAL" and slippage.confidence >= 0.7 else "ACCEPTABLE"
        if spread.spread_regime == "ELEVATED" or slippage.assumed_slippage_points >= 3:
            quality = "POOR"
        return FillResult(True, round(price, snapshot.digits), direction.upper(), quality, assumed_slippage_points=slippage.assumed_slippage_points, commission=commission.commission, metadata=metadata, execution_attempted=False)

    def _base_price(self, *, direction: str, snapshot: MarketSnapshot, is_entry: bool, base_price: float | None) -> float:
        direction = direction.upper()
        if base_price is not None:
            return base_price
        if is_entry:
            return snapshot.ask if direction == "BUY" else snapshot.bid
        return snapshot.bid if direction == "BUY" else snapshot.ask

    def _reject(self, code: str, reason: str, direction: str, metadata: Mapping[str, Any]) -> FillResult:
        return FillResult(False, None, direction.upper(), "REJECTED", reject_code=code, reject_reason=reason, metadata={**dict(metadata), "execution_simulation_version": SIMULATION_VERSION}, execution_attempted=False)


def _spread_percentile(spread: Any, snapshot: MarketSnapshot) -> float:
    if spread.p99_spread <= 0:
        return 50.0
    if abs(spread.p99_spread - snapshot.spread_points) < 1e-9 and spread.source == "tick":
        return 50.0
    return min(100.0, max(0.0, snapshot.spread_points / spread.p99_spread * 100.0))
