"""Exercise instrument geometry through the actual OHLC backtester."""

from decimal import Decimal

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting import Backtester, BacktestSettings, CostModel, TradeCandidate


def _bars(*, high=1.1004, low=1.0996):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC"),
        "open": [1.1, 1.1], "high": [high, high], "low": [low, low],
        "close": [1.1, 1.1], "spread_points": [0, 0],
    })


def _candidate(direction, **overrides):
    values = dict(timestamp="2026-01-01T00:00:00Z", symbol="GRID", direction=direction,
                  sl_price=1.099 if direction == "BUY" else 1.101,
                  tp_price=1.102 if direction == "BUY" else 1.098, lot=0.5)
    return TradeCandidate(**(values | overrides))


def _settings(**overrides):
    return BacktestSettings(**(dict(
        max_bars_in_trade=1,
        cost_model=CostModel(point=0.00001, tick_size=0.00005, tick_value=2,
                             slippage_points=1, commission_per_lot_round_turn=3),
    ) | overrides))


@pytest.mark.parametrize("direction,entry,exit", [("BUY", 1.10005, 1.09995), ("SELL", 1.09995, 1.10005)])
def test_backtester_uses_executable_tick_for_both_fills_and_money(direction, entry, exit):
    outcome = Backtester(_settings()).run(_bars(), [_candidate(direction)])
    assert not outcome.rejected_candidates
    trade, = outcome.trades
    assert trade.entry_price == entry
    assert trade.exit_price == exit
    # Two adverse executable ticks * $2 per tick * .5 lot, plus $1.5 commission.
    assert trade.profit == pytest.approx(-3.5)
    assert trade.tick_size == 0.00005


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
@pytest.mark.parametrize("field", ["sl_price", "tp_price"])
def test_off_grid_protection_is_rejected_without_rounding_history(direction, field):
    value = getattr(_candidate(direction), field)
    outcome = Backtester(_settings()).run(_bars(), [_candidate(direction, **{field: value + 0.00001})])
    assert outcome.trades == ()
    assert "tick grid" in outcome.rejected_candidates[0]["reason"]


@pytest.mark.parametrize("direction,stop", [("BUY", 1.10025), ("SELL", 1.09975)])
def test_trailing_protection_is_conservatively_aligned(direction, stop):
    outcome = Backtester(_settings(trailing_start_r=0.1, trailing_distance_points=11)).run(
        _bars(), [_candidate(direction)])
    trade, = outcome.trades
    assert trade.final_sl_price == stop
    assert Decimal(str(trade.final_sl_price)) % Decimal("0.00005") == 0


@pytest.mark.parametrize("direction,stop", [("BUY", 1.10005), ("SELL", 1.09995)])
def test_break_even_fractional_tick_lock_never_rounds_to_extra_profit(direction, stop):
    outcome = Backtester(_settings(break_even_trigger_r=0.1, break_even_lock_points=1)).run(
        _bars(), [_candidate(direction)])
    trade, = outcome.trades
    assert trade.final_sl_price == stop


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_price_estimator_placeholders_do_not_limit_candidate_lot(direction):
    outcome = Backtester(_settings()).run(_bars(), [_candidate(direction, lot=125)])
    trade, = outcome.trades
    # Lot constraints are checked by the instrument-aware caller, not by a
    # fabricated REPLAY snapshot whose lot=0 requests a price estimate only.
    assert trade.lot == 125
    assert trade.profit == pytest.approx(-875)


@pytest.mark.parametrize("direction,high,low", [("BUY", 1.1006, 1.0996), ("SELL", 1.1004, 1.0994)])
def test_exact_break_even_trigger_uses_declared_decimal_distances(direction, high, low):
    settings = _settings(
        cost_model=CostModel(point=0.00001, tick_size=0.00005, tick_value=2),
        break_even_trigger_r=0.6,
    )
    trade, = Backtester(settings).run(_bars(high=high, low=low), [_candidate(direction)]).trades
    assert trade.final_sl_price == 1.1
