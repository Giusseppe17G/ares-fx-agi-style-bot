"""Broker and tick inputs must not create false spread percentile changes."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.core.price_grid import spread_points_from_prices
from agi_style_forex_bot_mt5.data.tick_data import normalize_ticks
from agi_style_forex_bot_mt5.data.strategy_features import build_strategy_features
from agi_style_forex_bot_mt5.execution import MT5Connector

from test_execution_engine import FakeMT5
from test_shared_strategy_features import _bars, _snapshot


def _observed_quote():
    bars = _bars(221)
    expected = replace(_snapshot(bars, 220), bid=1.1, ask=1.10005)
    client = FakeMT5()
    client.symbol_info_tick = lambda symbol: SimpleNamespace(
        bid=expected.bid, ask=expected.ask, time=int(expected.timestamp_utc.timestamp()),
        time_msc=int(expected.timestamp_utc.timestamp() * 1000),
    )
    return bars, expected, client


def test_real_connector_and_explicit_quote_preserve_equal_spread_percentiles():
    bars, expected, client = _observed_quote()
    check, observed = MT5Connector(config=BotConfig(), mt5_client=client).ensure_symbol_snapshot(
        "EURUSD", now_utc=expected.timestamp_utc)
    assert check.accepted
    observed = replace(observed, timeframe="M5")
    assert observed.spread_points == expected.spread_points == 5
    forward = build_strategy_features(bars, observed)
    replay = build_strategy_features(bars, expected)
    assert forward["spread_percentile"] == replay["spread_percentile"] == 50
    assert forward == replay
    assert "order_send" not in client.calls and "order_check" not in client.calls


def test_tick_input_uses_the_same_exact_point_units():
    frame = normalize_ticks([{"timestamp_utc": "2026-01-05T12:00:00Z", "bid": 1.1, "ask": 1.10005}], point=.00001)
    assert frame.iloc[0].spread_points == 5


@pytest.mark.parametrize("field,value", [("bid", float("nan")), ("ask", float("inf")), ("bid", True), ("ask", None)])
def test_invalid_raw_quote_returns_rejection_without_exception_or_nan_payload(field, value):
    _, expected, client = _observed_quote()
    values = {"bid": expected.bid, "ask": expected.ask,
              "time": int(expected.timestamp_utc.timestamp()), "time_msc": int(expected.timestamp_utc.timestamp() * 1000)}
    values[field] = value
    client.symbol_info_tick = lambda symbol: SimpleNamespace(**values)
    check, observed = MT5Connector(config=BotConfig(), mt5_client=client).ensure_symbol_snapshot("EURUSD", now_utc=expected.timestamp_utc)
    assert not check.accepted and observed is None
    assert check.code == "MARKET_DATA_INVALID"
    import json
    json.dumps(check.payload, allow_nan=False)


@pytest.mark.parametrize("bid,ask,point,expected", [
    (1.1, 1.10005, .00001, 5), (1.101, 1.10105, .00001, 5),
    (150.123, 150.128, .001, 5), (1.1, 1.10025, .00001, 25),
    (1.1, 1.100250001, .00001, 25.0001), (1.1, 1.1000075, .00001, .75),
    (1.1, 1.1, .00001, 0),
])
def test_real_fractions_and_threshold_excess_are_not_rounded_away(bid, ask, point, expected):
    assert spread_points_from_prices(bid, ask, point) == expected


@pytest.mark.parametrize("bid,ask,point", [
    (0, 1, .01), (2, 1, .01), (1, 2, 0), (1, 2, -1),
    (1, 2, float("inf")), (1, 2, float("nan")), (1, 2, True),
    (1, 2, None), (1, 2, ".01"), (1, 1e308, 1e-320),
])
def test_invalid_spread_inputs_cannot_create_a_finite_accepted_cost(bid, ask, point):
    with pytest.raises(ValueError):
        spread_points_from_prices(bid, ask, point)
