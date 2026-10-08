"""Regressions for false VWAP values from otherwise finite market input."""
from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.data.indicators import add_indicators, approximate_vwap
from agi_style_forex_bot_mt5.data.market_data import MarketDataError, validate_ohlcv_frame


def _bars(prices: list[float], volumes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp_utc": pd.date_range("2026-01-01", periods=len(prices), freq="5min", tz="UTC"),
        **{key: prices for key in ("open", "high", "low", "close")},
        "volume": volumes, "spread_points": 0.0,
    })


@pytest.mark.parametrize("prices,volumes", [
    ([1e308], [1.0]),                         # Typical-price sum overflows.
    ([10.0], [1e308]),                       # Price times volume overflows.
    ([0.1, 0.2], [1e308, 1e308]),            # Cumulative volume overflows.
    ([2.0, 2.0], [5e307, 5e307]),            # Cumulative value overflows.
    ([1e-200], [1e-200]),                    # Positive product underflows to zero.
    ([10.0 + i / 100 for i in range(220)], [1e308] * 220),
])
def test_finite_inputs_with_unrepresentable_vwap_fail_closed(prices, volumes):
    bars = _bars(prices, volumes)
    validate_ohlcv_frame(bars)
    before = bars.copy(deep=True)
    with pytest.raises(MarketDataError, match="VWAP"):
        approximate_vwap(bars)
    pd.testing.assert_frame_equal(bars, before)


def test_all_zero_volume_is_an_explicit_typical_price_fallback():
    bars = _bars([10.0, 20.0, 30.0], [0.0, 0.0, 0.0])
    np.testing.assert_array_equal(approximate_vwap(bars), [10.0, 20.0, 30.0])


@pytest.mark.parametrize("key", ["high", "low", "close", "volume"])
@pytest.mark.parametrize("value", [Decimal("1e-1000"), 1 + 2j, True])
def test_lossy_nonreal_or_unnormalized_conversion_cannot_create_fallback(key, value):
    bars = _bars([1.0], [1.0])
    bars[key] = pd.Series([value])
    with pytest.raises(MarketDataError, match="VWAP requires normalized real numeric"):
        approximate_vwap(bars)


def test_initial_and_later_zero_volume_keep_defined_cumulative_semantics():
    bars = _bars([10.0, 20.0, 30.0, 40.0, 50.0], [0.0, 0.0, 2.0, 0.0, 6.0])
    np.testing.assert_array_equal(approximate_vwap(bars), [10.0, 20.0, 30.0, 30.0, 45.0])


def test_int64_prices_convert_before_typical_price_addition():
    bars = _bars([4_000_000_000_000_000_000] * 2, [1.0, 1.0])
    assert bars["close"].dtype == np.dtype("int64")
    np.testing.assert_array_equal(approximate_vwap(bars), [4e18, 4e18])


def test_ordinary_result_is_unchanged_and_causal_with_original_index():
    bars = _bars([1.10005 + i / 10000 for i in range(240)], [0.0, 0.0] + [100.0] * 238)
    bars.index = pd.Index(range(1000, 1240), name="source_row")
    typical = (bars.high + bars.low + bars.close) / 3.0
    original = ((typical * bars.volume).cumsum() / bars.volume.cumsum().replace(0.0, np.nan)).fillna(typical)
    actual = approximate_vwap(bars)
    pd.testing.assert_series_equal(actual, original)
    for count in (1, 2, 3, 14, 200):
        pd.testing.assert_series_equal(actual.iloc[:count], approximate_vwap(bars.iloc[:count]))


def test_feature_bundle_propagates_failure_instead_of_partial_features():
    bars = _bars([10.0 + i / 100 for i in range(220)], [1e308] * 220)
    with pytest.raises(MarketDataError, match="VWAP"):
        add_indicators(bars)
