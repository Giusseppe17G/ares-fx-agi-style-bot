"""Realized-trade metrics retain initial capital and each close-time observation."""

from dataclasses import asdict

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting.backtester import build_equity_curve, calculate_metrics


def _trade(profit, exit_time="2026-01-05T12:00:00Z", *, identity="one"):
    return {"signal_id": identity, "profit": profit, "r_multiple": profit / 10,
            "entry_time": exit_time, "exit_time": exit_time}


def _candles(*times):
    return pd.DataFrame({"timestamp": pd.to_datetime(times, utc=True),
                         "open": 1., "high": 1.1, "low": .9, "close": 1.})


def test_single_losing_trade_has_initial_baseline_and_first_period_loss():
    trades = [_trade(-10)]
    curve = build_equity_curve(trades, initial_balance=100)
    assert curve.equity.tolist() == [100., 90.]
    assert curve.timestamp.iloc[0] == curve.timestamp.iloc[1]
    metrics = calculate_metrics(trades, initial_balance=100)
    assert metrics.max_drawdown_pct == pytest.approx(-10)
    assert metrics.daily_max_drawdown_pct == pytest.approx(-10)
    assert metrics.worst_day_return_pct == pytest.approx(-10)
    assert metrics.worst_week_return_pct == pytest.approx(-10)
    assert metrics.worst_month_return_pct == pytest.approx(-10)
    assert metrics.monthly_returns == {"2026-01": -10.}
    assert metrics.recovery_factor == pytest.approx(-1)


def test_single_positive_first_period_is_not_replaced_by_zero():
    metrics = calculate_metrics([_trade(10)], initial_balance=100)
    assert metrics.worst_day_return_pct == pytest.approx(10)
    assert metrics.worst_week_return_pct == pytest.approx(10)
    assert metrics.worst_month_return_pct == pytest.approx(10)
    assert metrics.max_drawdown_pct == 0
    assert metrics.recovery_factor is None


@pytest.mark.parametrize("first,second,field", (
    ("2026-01-05T12:00:00Z", "2026-01-06T12:00:00Z", "worst_day_return_pct"),
    ("2026-01-04T12:00:00Z", "2026-01-05T12:00:00Z", "worst_week_return_pct"),
    ("2026-01-31T12:00:00Z", "2026-02-01T12:00:00Z", "worst_month_return_pct"),
))
def test_first_calendar_period_is_included_before_later_period_changes(first, second, field):
    metrics = calculate_metrics([_trade(-20, first), _trade(-10, second, identity="two")], initial_balance=100)
    assert getattr(metrics, field) == pytest.approx(-20)
    if field == "worst_month_return_pct":
        assert metrics.monthly_returns == {"2026-01": -20., "2026-02": -12.5}
        assert metrics.worst_month_return_pct == min(metrics.monthly_returns.values())


def test_daily_drawdown_includes_first_close_relative_to_previous_day_equity():
    trades = [_trade(100), _trade(-50, "2026-01-06T12:00:00Z", identity="two"),
              _trade(10, "2026-01-06T13:00:00Z", identity="three")]
    metrics = calculate_metrics(trades, initial_balance=100)
    assert metrics.daily_max_drawdown_pct == pytest.approx(-25)
    assert metrics.worst_day_return_pct == pytest.approx(-20)


@pytest.mark.parametrize("with_candles", (False, True))
def test_simultaneous_closes_are_one_net_realization_without_invented_intrinsic_order(with_candles):
    trades = [_trade(-50, identity="loss"), _trade(40, identity="gain")]
    candles = _candles(trades[0]["exit_time"]) if with_candles else None
    curve = build_equity_curve(trades, initial_balance=100, candles=candles)
    assert curve.equity.tolist() == [100., 90.]
    metrics = calculate_metrics(trades, initial_balance=100, equity_curve=curve)
    assert metrics.net_profit == -10
    assert metrics.max_drawdown_pct == pytest.approx(-10)
    reversed_curve = build_equity_curve(reversed(trades), initial_balance=100, candles=candles)
    pd.testing.assert_frame_equal(curve, reversed_curve)


def test_candles_do_not_delay_or_hide_realizations_between_bars():
    trades = [_trade(100, "2026-01-05T00:30:00Z"), _trade(-100, "2026-01-05T01:00:00Z", identity="two")]
    curve = build_equity_curve(trades, initial_balance=100,
                               candles=_candles("2026-01-05T02:00:00Z", "2026-01-05T00:00:00Z"))
    assert curve.equity.tolist() == [100., 200., 100., 100.]
    assert curve.timestamp.is_monotonic_increasing
    assert pd.Timestamp(trades[0]["exit_time"]) in set(curve.timestamp)
    assert calculate_metrics(trades, initial_balance=100, equity_curve=curve).max_drawdown_pct == -50


def test_realization_on_first_candle_retains_pre_close_capital():
    trades = [_trade(-10, "2026-01-05T00:00:00Z"), _trade(20, "2026-01-05T01:00:00Z", identity="two"),
              _trade(-15, "2026-01-05T01:00:00Z", identity="three")]
    curve = build_equity_curve(trades, initial_balance=100,
                               candles=_candles("2026-01-05T00:00:00Z", "2026-01-05T02:00:00Z"))
    assert curve.equity.tolist() == [100., 90., 95., 95.]
    assert calculate_metrics(trades, initial_balance=100, equity_curve=curve).max_drawdown_pct == -10


def test_recovery_uses_largest_money_drawdown_even_if_percentage_peak_is_elsewhere():
    trades = [_trade(-20), _trade(120, "2026-01-06T12:00:00Z", identity="two"),
              _trade(-30, "2026-01-07T12:00:00Z", identity="three")]
    metrics = calculate_metrics(trades, initial_balance=100)
    # Equity 100 -> 80 -> 200 -> 170. Maximum percent drawdown is 20%,
    # but the largest monetary decline is 30 from the later 200 peak.
    assert metrics.max_drawdown_pct == -20
    assert metrics.net_profit == 70
    assert metrics.recovery_factor == pytest.approx(70 / 30)


def test_metrics_order_realized_trades_chronologically_without_mutating_inputs():
    ordered = [_trade(-10, "2026-01-05T10:00:00Z", identity="one"),
               _trade(-20, "2026-01-05T11:00:00Z", identity="two"),
               _trade(-30, "2026-01-05T12:00:00Z", identity="three"),
               _trade(70, "2026-01-05T13:00:00Z", identity="four")]
    shuffled = [ordered[3], ordered[1], ordered[0], ordered[2]]
    original_order = [trade["signal_id"] for trade in shuffled]
    first = calculate_metrics(ordered, initial_balance=100)
    second = calculate_metrics(shuffled, initial_balance=100)
    assert asdict(first) == asdict(second)
    assert second.max_consecutive_losses == 3
    assert [trade["signal_id"] for trade in shuffled] == original_order


def test_monthly_grouping_uses_utc_close_date():
    metrics = calculate_metrics([_trade(-10, "2026-02-01T00:30:00+02:00")], initial_balance=100)
    assert metrics.monthly_returns == {"2026-01": -10.}
    assert metrics.worst_month_return_pct == -10


def test_provided_unsorted_curve_without_baseline_still_counts_initial_loss():
    trades = [_trade(-10), _trade(20, "2026-01-06T12:00:00Z", identity="two")]
    curve = pd.DataFrame({"timestamp": [trades[1]["exit_time"], trades[0]["exit_time"]], "equity": [110., 90.]})
    before = curve.copy(deep=True)
    metrics = calculate_metrics(trades, initial_balance=100, equity_curve=curve)
    assert metrics.max_drawdown_pct == -10
    assert metrics.daily_max_drawdown_pct == -10
    assert metrics.worst_day_return_pct == -10
    pd.testing.assert_frame_equal(curve, before)


def test_empty_trade_history_preserves_flat_initial_capital():
    curve = build_equity_curve([], initial_balance=100)
    assert curve.equity.tolist() == [100.]
    metrics = calculate_metrics([], initial_balance=100)
    assert metrics.max_drawdown_pct == metrics.daily_max_drawdown_pct == 0
    assert metrics.worst_day_return_pct == metrics.worst_week_return_pct == metrics.worst_month_return_pct == 0
    assert metrics.recovery_factor is None
