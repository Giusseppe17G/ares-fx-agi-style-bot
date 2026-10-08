"""Executable tick grids and fail-closed fill inputs across shared adapters."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agi_style_forex_bot_mt5.contracts import Direction, EntryType, MarketSnapshot, RiskDecision, SignalAction, TradeSignal
from agi_style_forex_bot_mt5.core.clock import FrozenClock
from agi_style_forex_bot_mt5.core.decision.signal_builder import build_signal_prices
from agi_style_forex_bot_mt5.core.execution.shared_fill import SharedFillModel
from agi_style_forex_bot_mt5.core.price_grid import adverse_fill_price, snap_price_to_tick
from agi_style_forex_bot_mt5.execution_simulation import FillModel, SlippageModel
from agi_style_forex_bot_mt5.paper_trading.paper_fill_model import PaperFillModel
from agi_style_forex_bot_mt5.paper_trading.paper_position_manager import PaperPositionManager
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def snapshot(**changes):
    return replace(MarketSnapshot("EURUSD", "M5", NOW, 1.1, 1.1001, 10, 5,
        0.00001, 5, 0.00005, 0.01, 100, 0.01, 0, 0), **changes)


def on_grid(price, tick_size):
    return Decimal(str(price)) % Decimal(str(tick_size)) == 0


@pytest.mark.parametrize("direction,entry,expected", (("BUY", True, 1.10015),
    ("SELL", True, 1.10005), ("BUY", False, 1.10005), ("SELL", False, 1.10015)))
def test_adverse_execution_rounding_uses_tick_size_not_digits(direction, entry, expected):
    assert adverse_fill_price(base_price=1.1001, point=0.00001, slippage_points=1,
        tick_size=0.00005, direction=direction, is_entry=entry) == expected


@pytest.mark.parametrize("direction", ("BUY", "SELL"))
@pytest.mark.parametrize("slippage", (0, 0.1, 0.6, 1, 2.5, 5))
@pytest.mark.parametrize("tick", (0.00001, 0.00005))
def test_paper_and_shared_fills_match_exactly_at_executable_prices(direction, slippage, tick):
    quote = snapshot(tick_size=tick)
    shared = SharedFillModel(slippage_points=slippage)
    paper = PaperFillModel(slippage_points=slippage, clock=FrozenClock(NOW))
    pairs = ((shared.entry(direction=direction, snapshot=quote, lot=0.1, replay=True),
              paper.entry_result(direction=direction, snapshot=quote, lot=0.1)),
             (shared.exit(direction=direction, snapshot=quote, lot=0.1, base_price=1.0991, replay=True),
              paper.exit_result(direction=direction, snapshot=quote, lot=0.1, base_price=1.0991)))
    for replay, live in pairs:
        assert replay.accepted and live.accepted
        assert replay.to_dict() == live.to_dict()
        assert on_grid(replay.fill_price, tick)
        assert replay.execution_attempted is False


@pytest.mark.parametrize("direction,base", (("BUY", 1.10313), ("SELL", 1.09703)))
def test_take_profit_price_never_improves_with_grid_rounding(direction, base):
    result = SharedFillModel(slippage_points=0).exit(direction=direction,
        snapshot=snapshot(), base_price=base, replay=True)
    assert result.accepted and on_grid(result.fill_price, 0.00005)
    assert result.fill_price <= base if direction == "BUY" else result.fill_price >= base


@pytest.mark.parametrize("action", (SignalAction.BUY, SignalAction.SELL))
def test_signal_protections_move_toward_entry_before_risk_sizing(action):
    quote = snapshot()
    sl, tp = build_signal_prices(quote, action, 0.00103)
    old_sl, old_tp = build_signal_prices(replace(quote, tick_size=quote.point), action, 0.00103)
    assert on_grid(sl, quote.tick_size) and on_grid(tp, quote.tick_size)
    if action == SignalAction.BUY:
        assert old_sl <= sl < quote.ask < tp <= old_tp
    else:
        assert old_tp <= tp < quote.bid < sl <= old_sl


@pytest.mark.parametrize("action", (SignalAction.BUY, SignalAction.SELL))
def test_ordinary_point_tick_signal_policy_is_preserved(action):
    quote = snapshot(tick_size=0.00001)
    reference = quote.ask if action == SignalAction.BUY else quote.bid
    sign = 1 if action == SignalAction.BUY else -1
    atr = 0.001037
    assert build_signal_prices(quote, action, atr) == (
        round(reference - sign * atr, quote.digits), round(reference + sign * atr * 1.8, quote.digits))


def test_tick_grid_that_collapses_protections_is_rejected():
    with pytest.raises(ValueError, match="collapses"):
        build_signal_prices(snapshot(tick_size=0.1), SignalAction.SELL, 0.001)


def test_float_representation_noise_does_not_add_a_whole_tick():
    ask = 1.00001 + 18 * 0.00001  # 1.0001900000000001
    assert adverse_fill_price(base_price=ask, point=0.00001, slippage_points=1,
        tick_size=0.00001, direction="BUY", is_entry=True) == 1.0002
    # A real fraction of a point still rounds adversely.
    assert adverse_fill_price(base_price=1.000190001, point=0.00001, slippage_points=1,
        tick_size=0.00001, direction="BUY", is_entry=True) == 1.00021


@pytest.mark.parametrize("value", (float("nan"), float("inf"), -1, True, "1"))
def test_invalid_numeric_tick_age_is_rejected(value):
    result = SharedFillModel().entry(direction="BUY", snapshot=snapshot(), context={"tick_age_seconds": value})
    assert not result.accepted and result.reject_code == "CONTEXT_INVALID"


@pytest.mark.parametrize("field", ("bid", "ask", "point", "tick_size", "tick_value", "volume_min", "spread_points"))
@pytest.mark.parametrize("value", (float("nan"), float("inf"), True))
def test_nonfinite_or_boolean_snapshot_cannot_produce_a_fill(field, value):
    result = SharedFillModel().entry(direction="BUY", snapshot=snapshot(**{field: value}), replay=True)
    assert not result.accepted and result.reject_code == "SNAPSHOT_INVALID"


@pytest.mark.parametrize("changes", ({"symbol": 1}, {"digits": True}, {"timestamp_utc": NOW.replace(tzinfo=None)}))
def test_missing_snapshot_types_are_rejected(changes):
    result = SharedFillModel().entry(direction="BUY", snapshot=snapshot(**changes), replay=True)
    assert not result.accepted and result.reject_code == "SNAPSHOT_INVALID"


def test_future_timestamp_without_replay_override_is_rejected():
    quote = snapshot(timestamp_utc=datetime.now(timezone.utc) + timedelta(days=1))
    result = SharedFillModel().entry(direction="BUY", snapshot=quote)
    assert not result.accepted and result.reject_code == "TICK_TIME_INVALID"


@pytest.mark.parametrize("lot", (float("nan"), float("inf"), -0.1, True, 0.001, 0.015, 101))
def test_invalid_or_unexecutable_lot_is_rejected(lot):
    result = SharedFillModel().entry(direction="BUY", snapshot=snapshot(), lot=lot, replay=True)
    assert not result.accepted and result.reject_code == "FILL_INPUT_INVALID"


@pytest.mark.parametrize("direction", (None, True, "LONG", ""))
def test_invalid_direction_cannot_default_to_sell(direction):
    result = SharedFillModel().entry(direction=direction, snapshot=snapshot(), replay=True)
    assert not result.accepted and result.reject_code == "DIRECTION_INVALID"


@pytest.mark.parametrize("field", ("slippage_points", "commission_per_lot_round_turn", "max_spread_points"))
@pytest.mark.parametrize("value", (float("nan"), float("inf"), -1, True))
def test_invalid_shared_cost_config_fails_at_construction(field, value):
    with pytest.raises(ValueError):
        SharedFillModel(**{field: value})


def test_corrupted_cost_estimate_cannot_produce_nan_fill():
    class CorruptSlippage(SlippageModel):
        def estimate(self, context):
            return replace(super().estimate(context), assumed_slippage_points=float("nan"))
    result = FillModel(slippage_model=CorruptSlippage()).market_entry(direction="BUY",
        snapshot=snapshot(), context={"tick_age_seconds": 0})
    assert not result.accepted and result.reject_code == "SIMULATION_INVALID"


@pytest.mark.parametrize("direction", (Direction.BUY, Direction.SELL))
def test_coarse_tick_slippage_stays_inside_approved_budget_on_open_and_stop(tmp_path, direction):
    quote = snapshot()
    sl, tp = build_signal_prices(quote, SignalAction(direction.value), 0.00103)
    signal = TradeSignal("grid-budget", NOW, "EURUSD", "M5", direction, EntryType.MARKET, sl, tp, risk_pct=0.5)
    risk = RiskDecision("grid-budget", True, approved_lot=0.5, risk_amount_account_currency=50,
        checks={"effective_risk_pct": 0.5, "account_equity": {"status": "passed", "equity": 10_000}})
    database = TelemetryDatabase(tmp_path / "grid.sqlite3")
    try:
        manager = PaperPositionManager(database=database,
            fill_model=PaperFillModel(slippage_points=1, commission_per_lot_round_turn=7, clock=FrozenClock(NOW)))
        trade = manager.open_trade(signal=signal, risk_decision=risk, snapshot=quote, broker_symbol="EURUSD",
            score=90, reasons=("fixture",), strategy_name="grid", strategy_version="1", regime="TREND", session="LONDON")
        assert trade.lot < 0.5 and trade.risk_amount <= 50
        assert on_grid(trade.entry_price, quote.tick_size)
        assert trade.metadata["fill_risk_reconciliation"]["exit_slippage_reserve_per_lot"] == 5
        closed = manager.close_trade(trade, quote, "SL", trade.sl_price)
        assert on_grid(closed.exit_price, quote.tick_size)
        assert -closed.profit == pytest.approx(trade.risk_amount)
        assert -closed.profit <= 50
    finally:
        database.close()
