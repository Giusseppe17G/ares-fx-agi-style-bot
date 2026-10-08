"""The existing paper stop policy, driven by measured closed-bar ATR."""

from math import isfinite

from ...contracts import Direction, EntryType, MarketSnapshot, SignalAction, StrategySignal, TradeSignal
from ...strategy.strategy_ensemble import STRATEGY_VERSION
from ..price_grid import snap_price_to_tick
from .pipeline import DecisionContext


def build_signal_prices(snapshot: MarketSnapshot, action: SignalAction, atr: float) -> tuple[float, float]:
    """The shared stop policy; retain the 100-point floor and 1.8 reward/risk."""
    if isinstance(atr, bool) or not isinstance(atr, (int, float)) or not isfinite(atr) or atr <= 0:
        raise ValueError("positive finite measured ATR is required")
    if action not in {SignalAction.BUY, SignalAction.SELL}:
        raise ValueError("a directional strategy signal is required")
    snapshot.validate()
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
               for value in (snapshot.bid, snapshot.ask, snapshot.point, snapshot.tick_size, snapshot.stops_level_points)):
        raise ValueError("finite market prices and stop constraints are required")
    reference = snapshot.ask if action == SignalAction.BUY else snapshot.bid
    distance = max(atr, snapshot.point * 100, snapshot.stops_level_points * snapshot.point * 2)
    sign = 1 if action == SignalAction.BUY else -1
    # Preserve the existing display precision policy, then bring both protections
    # toward entry on coarser executable grids. Sizing sees the final prices.
    sl = snap_price_to_tick(round(reference - sign * distance, snapshot.digits), snapshot.tick_size,
                            rounding="up" if sign == 1 else "down")
    tp = snap_price_to_tick(round(reference + sign * distance * 1.8, snapshot.digits), snapshot.tick_size,
                            rounding="down" if sign == 1 else "up")
    minimum = snapshot.stops_level_points * snapshot.point
    if not (sign * (reference - sl) > 0 and sign * (tp - reference) > 0):
        raise ValueError("broker tick grid collapses entry protections")
    if min(abs(reference - sl), abs(tp - reference)) + snapshot.point * 1e-9 < minimum:
        raise ValueError("broker tick grid violates minimum stop distance")
    return sl, tp


def build_trade_signal(context: DecisionContext, strategy: StrategySignal) -> TradeSignal:
    """Construct a candidate from measured closed-bar ATR and stable identity."""
    snapshot = context.snapshot
    atr = context.features.get("atr")
    sl_price, tp_price = build_signal_prices(snapshot, strategy.action, atr)
    direction = Direction(strategy.action.value)
    reference = snapshot.ask if direction == Direction.BUY else snapshot.bid
    signal = TradeSignal(
        signal_id=context.decision_id, created_at_utc=snapshot.timestamp_utc,
        symbol=snapshot.symbol, timeframe=snapshot.timeframe, direction=direction,
        entry_type=EntryType.MARKET, sl_price=sl_price, tp_price=tp_price,
        risk_pct=context.config.max_risk_per_trade_pct, confidence=strategy.score / 100.0,
        strategy_name=strategy.strategy_name, strategy_version=str(strategy.metadata.get("version", STRATEGY_VERSION)),
        reason="; ".join(strategy.reasons), metadata={**strategy.metadata, "atr": atr,
            "reference_price": reference, "features_available_at_utc": context.features_available_at_utc.isoformat()},
    )
    signal.validate_against_snapshot(snapshot)
    return signal
