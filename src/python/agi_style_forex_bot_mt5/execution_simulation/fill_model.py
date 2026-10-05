"""Refined fill simulation for shadow/paper execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from math import isfinite
from typing import Any, Mapping

from agi_style_forex_bot_mt5.contracts import MarketSnapshot
from agi_style_forex_bot_mt5.core.price_grid import adverse_fill_price

from .commission_model import CommissionModel
from .gap_model import GapModel
from .latency_model import LatencyModel
from .partial_fill_model import PartialFillModel
from .slippage_model import SlippageModel
from .spread_model import SpreadModel

SIMULATION_VERSION = "execution_simulation_v2_tick_grid"


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
        _finite_nonnegative(max_spread_points, "max_spread_points")
        _finite_nonnegative(max_tick_age_seconds, "max_tick_age_seconds")
        if max_tick_age_seconds <= 0:
            raise ValueError("max_tick_age_seconds must be positive")
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
        if not isinstance(direction, str) or direction.upper() not in {"BUY", "SELL"}:
            return self._reject("DIRECTION_INVALID", "direction must be BUY or SELL", direction, {})
        direction = direction.upper()
        try:
            _finite_nonnegative(self.max_spread_points, "max_spread_points")
            _finite_nonnegative(self.max_tick_age_seconds, "max_tick_age_seconds")
            if self.max_tick_age_seconds <= 0:
                raise ValueError("tick age limit must be positive")
        except (ValueError, TypeError):
            return self._reject("CONFIG_INVALID", "simulation limits must be finite and valid", direction, {})
        try:
            context = dict(context or {})
            for name in ("tick_age_seconds", "atr_points", "broker_readiness_score", "data_read_latency_ms"):
                if name in context:
                    _finite_nonnegative(context[name], name)
        except (ValueError, TypeError):
            return self._reject("CONTEXT_INVALID", "simulation context must contain finite non-negative values", direction, {})
        try:
            _validate_snapshot_inputs(snapshot)
            snapshot.validate()
        except (ValueError, TypeError, AttributeError, OverflowError):
            return self._reject("SNAPSHOT_INVALID", "snapshot metadata is invalid", direction, {})
        try:
            _validate_lot(lot, snapshot)
            if base_price is not None:
                _finite_nonnegative(base_price, "base_price")
                if base_price <= 0:
                    raise ValueError("base_price must be positive")
        except (ValueError, TypeError):
            return self._reject("FILL_INPUT_INVALID", "lot or base price is invalid", direction, {})
        if bool(context.get("market_closed", False)):
            return self._reject("MARKET_CLOSED", "market appears closed", direction, {})
        tick_age = context.get("tick_age_seconds")
        if tick_age is None:
            tick_age = (datetime.now(timezone.utc) - snapshot.timestamp_utc.astimezone(timezone.utc)).total_seconds()
        if not isfinite(tick_age) or tick_age < 0:
            return self._reject("TICK_TIME_INVALID", "tick timestamp is invalid or from the future", direction, {})
        if tick_age > self.max_tick_age_seconds:
            return self._reject("TICK_STALE", "tick is stale", direction, {"tick_age_seconds": tick_age})
        spread = self.spread_model.estimate(symbol=snapshot.symbol, snapshot=snapshot, forward_spreads=context.get("forward_spreads", ()))
        if not spread.trade_allowed_by_spread:
            return self._reject(
                spread.reject_reason or "SPREAD_EXTREME",
                "spread exceeds maximum" if spread.spread_regime == "EXTREME" else "spread evidence is missing or invalid",
                direction, {"spread": spread.to_dict()},
            )
        partial = self.partial_fill_model.decide(requested_lot=lot, context={"spread_extreme": spread.spread_regime == "EXTREME", **context})
        if partial.status.startswith("REJECTED"):
            return self._reject(partial.status, partial.reject_reason, direction, {"partial_fill": partial.to_dict(), "spread": spread.to_dict()})
        if partial.status != "FULL_FILL" or partial.filled_lot != lot:
            return self._reject("PARTIAL_FILL_UNSUPPORTED", "fill quantity must match the approved request", direction, {})
        try:
            slippage = self.slippage_model.estimate({**context, "spread_percentile": _spread_percentile(spread, snapshot)})
            commission = self.commission_model.estimate(lot=lot, symbol=snapshot.symbol)
            latency = self.latency_model.estimate(context)
            for name, value in (("slippage", slippage.assumed_slippage_points), ("commission", commission.commission),
                                ("confidence", slippage.confidence), ("latency", latency.decision_to_fill_delay_ms)):
                _finite_nonnegative(value, name)
            base = self._base_price(direction=direction, snapshot=snapshot, is_entry=is_entry, base_price=base_price)
            price = adverse_fill_price(base_price=base, point=snapshot.point,
                slippage_points=slippage.assumed_slippage_points, tick_size=snapshot.tick_size,
                direction=direction, is_entry=is_entry)
        except (ValueError, TypeError, ArithmeticError):
            return self._reject("SIMULATION_INVALID", "execution cost or executable price is invalid", direction, {})
        metadata = {
            "execution_simulation_version": SIMULATION_VERSION,
            "spread_model_used": spread.to_dict(),
            "slippage_model_used": slippage.to_dict(),
            "commission_model_used": commission.to_dict(),
            "latency_assumption": latency.to_dict(),
            "partial_fill": partial.to_dict(),
            "ambiguity_flags": tuple(context.get("ambiguity_flags", ())),
            "price_grid": {"tick_size": snapshot.tick_size, "rounding": "adverse",
                           "effective_slippage_points": float(abs(Decimal(str(price)) - Decimal(str(base))) / Decimal(str(snapshot.point)))},
        }
        quality = "GOOD" if spread.spread_regime == "NORMAL" and slippage.confidence >= 0.7 else "ACCEPTABLE"
        if spread.spread_regime == "ELEVATED" or slippage.assumed_slippage_points >= 3:
            quality = "POOR"
        return FillResult(True, price, direction.upper(), quality, assumed_slippage_points=slippage.assumed_slippage_points, commission=commission.commission, metadata=metadata, execution_attempted=False)

    def _base_price(self, *, direction: str, snapshot: MarketSnapshot, is_entry: bool, base_price: float | None) -> float:
        direction = direction.upper()
        if base_price is not None:
            return base_price
        if is_entry:
            return snapshot.ask if direction == "BUY" else snapshot.bid
        return snapshot.bid if direction == "BUY" else snapshot.ask

    def _reject(self, code: str, reason: str, direction: str, metadata: Mapping[str, Any]) -> FillResult:
        return FillResult(False, None, direction.upper() if isinstance(direction, str) else "", "REJECTED", reject_code=code, reject_reason=reason, metadata={**dict(metadata), "execution_simulation_version": SIMULATION_VERSION}, execution_attempted=False)


def _finite_nonnegative(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


def _validate_snapshot_inputs(snapshot: MarketSnapshot) -> None:
    if not isinstance(snapshot.symbol, str) or not snapshot.symbol.strip():
        raise ValueError("symbol is required")
    if not isinstance(snapshot.timeframe, str) or not snapshot.timeframe.strip():
        raise ValueError("timeframe is required")
    timestamp = snapshot.timestamp_utc
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("aware timestamp is required")
    for name in ("bid", "ask", "spread_points", "point", "tick_value", "tick_size", "volume_min", "volume_max",
                 "volume_step", "stops_level_points", "freeze_level_points"):
        _finite_nonnegative(getattr(snapshot, name), name)
    if isinstance(snapshot.digits, bool) or not isinstance(snapshot.digits, int) or not 0 <= snapshot.digits <= 323:
        raise ValueError("display precision is invalid")
    point, tick = Decimal(str(snapshot.point)), Decimal(str(snapshot.tick_size))
    if point <= 0 or tick <= 0 or point != Decimal(1).scaleb(-snapshot.digits) or tick % point != 0:
        raise ValueError("display precision and executable tick grid are inconsistent")


def _validate_lot(lot: float, snapshot: MarketSnapshot) -> None:
    _finite_nonnegative(lot, "lot")
    # Zero requests only a price estimate; order sinks still require positive lots.
    if lot == 0:
        return
    value, minimum, maximum, step = (Decimal(str(item)) for item in
        (lot, snapshot.volume_min, snapshot.volume_max, snapshot.volume_step))
    if value < minimum or value > maximum or (value - minimum) % step != 0:
        raise ValueError("lot violates broker volume constraints")


def _spread_percentile(spread: Any, snapshot: MarketSnapshot) -> float:
    if spread.p99_spread <= 0:
        return 50.0
    if abs(spread.p99_spread - snapshot.spread_points) < 1e-9 and spread.source == "tick":
        return 50.0
    return min(100.0, max(0.0, snapshot.spread_points / spread.p99_spread * 100.0))
