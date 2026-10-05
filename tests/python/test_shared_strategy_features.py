"""Causal feature and independent market-structure parity regressions."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.contracts import MarketSnapshot
from agi_style_forex_bot_mt5.data.market_data import MarketDataError
from agi_style_forex_bot_mt5.data.strategy_features import (
    build_strategy_features, closed_strategy_bars, prepare_strategy_features, strategy_features_at,
)


def _bars(count=340):
    x = np.arange(count)
    close = 1.1 + 0.001 * np.sin(x / 4) + x * 0.000002
    open_price = close - 0.00002 * np.cos(x)
    return pd.DataFrame({
        "timestamp_utc": pd.date_range("2026-01-05", periods=count, freq="5min", tz="UTC"),
        "open": open_price, "close": close,
        "high": np.maximum(open_price, close) + 0.0001,
        "low": np.minimum(open_price, close) - 0.0001,
        "volume": 100 + x % 30, "spread_points": np.full(count, 5.0),
    })


def _snapshot(bars, idx):
    row = bars.iloc[idx]
    return MarketSnapshot(
        "EURUSD", "M5", (row.timestamp_utc + pd.Timedelta(minutes=5)).to_pydatetime(),
        float(row.close), float(row.close) + 0.00005, 5, 5, 0.00001,
        1, 0.00001, 0.01, 100, 0.01, 10, 5,
    )


@pytest.mark.parametrize("idx", (220, 251, 300))
def test_batch_features_equal_closed_prefix_without_future_dependency(idx):
    bars = _bars()
    snapshot = _snapshot(bars, idx)
    full = prepare_strategy_features(bars, point=snapshot.point)
    from_full = strategy_features_at(full, idx, snapshot)
    from_prefix = build_strategy_features(bars.iloc[:idx + 1], snapshot)
    assert from_full == from_prefix

    altered_future = bars.copy()
    altered_future.loc[idx + 1:, ["open", "high", "low", "close"]] *= 5
    changed = prepare_strategy_features(altered_future, point=snapshot.point)
    assert strategy_features_at(changed, idx, snapshot) == from_prefix


def test_pivot_extreme_is_exposed_only_after_two_confirmation_candles():
    bars = _bars()
    bars.loc[220, "high"] = 2.0
    bars.loc[250, "low"] = 0.5
    frame = prepare_strategy_features(bars, point=0.00001)
    assert frame.loc[220, "latest_swing_high"] < 1.2
    assert frame.loc[221, "latest_swing_high"] < 1.2
    assert frame.loc[222, "latest_swing_high"] == 2.0
    assert frame.loc[250, "latest_swing_low"] > 1.0
    assert frame.loc[251, "latest_swing_low"] > 1.0
    assert frame.loc[252, "latest_swing_low"] == 0.5


def test_breakout_levels_exclude_signal_candle_and_ties_are_not_spread_spikes():
    bars = _bars()
    idx = len(bars) - 1
    prior = bars.iloc[idx - 20:idx]
    bars.loc[idx, "high"] = float(prior.high.max()) + 0.02
    features = build_strategy_features(bars, _snapshot(bars, idx))
    assert features["resistance"] == prior.high.max()
    assert features["support"] == prior.low.min()
    assert features["prev_high"] == features["prior_high"]
    assert features["spread_percentile"] == 50
    assert features["swept_prev_high"] is True


def test_real_session_uses_decision_time_at_closed_candle_boundary():
    bars = _bars(400)
    # A 06:55 bar first becomes usable at 07:00 UTC, the London boundary.
    bars["timestamp_utc"] = pd.date_range("2026-01-04T00:00Z", periods=400, freq="5min")
    idx = 371
    features = build_strategy_features(bars.iloc[:idx + 1], _snapshot(bars, idx))
    assert features["session"] == "LONDON"
    assert features["available_at_utc"] == "2026-01-05T07:00:00+00:00"
    rollover = replace(_snapshot(bars, idx), timestamp_utc=pd.Timestamp("2026-01-05T21:00Z").to_pydatetime())
    assert build_strategy_features(bars.iloc[:idx + 1], rollover)["session"] == "ROLLOVER"


@pytest.mark.parametrize("failure", ("unclosed", "point", "warmup", "missing_spread", "duplicate", "unknown_timeframe"))
def test_incomplete_or_incompatible_feature_inputs_fail_closed(failure):
    bars = _bars()
    snapshot = _snapshot(bars, len(bars) - 1)
    if failure == "unclosed":
        snapshot = replace(snapshot, timestamp_utc=bars.iloc[-1].timestamp_utc.to_pydatetime())
    elif failure == "warmup":
        bars = bars.iloc[:30]
    elif failure == "missing_spread":
        bars = bars.drop(columns="spread_points")
    elif failure == "duplicate":
        bars.loc[len(bars) - 1, "timestamp_utc"] = bars.iloc[-2].timestamp_utc
    elif failure == "unknown_timeframe":
        snapshot = replace(snapshot, timeframe="UNKNOWN")
    with pytest.raises((MarketDataError, ValueError)):
        if failure == "point":
            frame = prepare_strategy_features(bars, point=0.001)
            strategy_features_at(frame, len(frame) - 1, snapshot)
        elif failure == "unclosed":
            frame = prepare_strategy_features(bars, point=snapshot.point)
            strategy_features_at(frame, len(frame) - 1, snapshot)
        else:
            build_strategy_features(bars, snapshot)


def test_forming_bar_changes_cannot_change_live_features():
    bars = _bars()
    snapshot = _snapshot(bars, len(bars) - 2)
    before = build_strategy_features(bars, snapshot)
    bars.loc[len(bars) - 1, ["open", "high", "low", "close"]] *= 10
    bars.loc[len(bars) - 1, "volume"] = 1e9
    bars.loc[len(bars) - 1, "spread_points"] = 1e6
    assert build_strategy_features(bars, snapshot) == before
    assert len(closed_strategy_bars(bars, snapshot)) == len(bars) - 1


def test_closed_history_rejects_empty_or_naive_timestamps():
    bars = _bars()
    snapshot = _snapshot(bars, len(bars) - 1)
    with pytest.raises(MarketDataError):
        closed_strategy_bars(bars, replace(snapshot, timestamp_utc=bars.iloc[0].timestamp_utc.to_pydatetime()))
    bars["timestamp_utc"] = bars["timestamp_utc"].dt.tz_localize(None)
    with pytest.raises(MarketDataError):
        closed_strategy_bars(bars, snapshot)


@pytest.mark.parametrize("field", ("bid", "ask", "spread_points", "tick_value", "volume_min"))
def test_non_finite_snapshot_cannot_enter_feature_builder(field):
    bars = _bars()
    snapshot = replace(_snapshot(bars, len(bars) - 1), **{field: float("nan")})
    with pytest.raises(MarketDataError):
        build_strategy_features(bars, snapshot)
