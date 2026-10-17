"""Bid-bar exit fills, gaps, exit-bar spread and daily metrics; synthetic, no broker."""

import math

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting import backtester as bt
from agi_style_forex_bot_mt5.backtesting import Backtester, BacktestSettings, CostModel, TradeCandidate

POINT = 0.00001
WEEKDAYS_PER_YEAR = 365.25 / 7 * 5


def frame(rows, *, start="2026-01-05", freq="5min"):
    """Bars are bid quotes: (open, high, low, close, spread_points)."""
    stamps = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    o, h, l, c, s = zip(*rows)
    return pd.DataFrame({"timestamp": stamps, "open": o, "high": h, "low": l, "close": c, "spread_points": s})


def run(bars, direction, sl, tp, **overrides):
    settings = BacktestSettings(**({"cost_model": CostModel(max_spread_points=25)} | overrides))
    candidate = TradeCandidate(timestamp=bars.timestamp[0], symbol="EURUSD", direction=direction,
                               sl_price=sl, tp_price=tp, lot=1.0)
    return Backtester(settings).run(bars, [candidate])


def only_trade(outcome):
    assert outcome.rejected_candidates == ()
    trade, = outcome.trades
    return trade


def test_buy_gap_through_stop_fills_at_the_worse_open():
    bars = frame([(1.1, 1.1002, 1.0999, 1.1, 0), (1.095, 1.0955, 1.0945, 1.095, 0)])
    trade = only_trade(run(bars, "BUY", 1.099, 1.102))
    assert trade.exit_reason == "SL"
    assert trade.exit_price == 1.095
    assert trade.profit == pytest.approx(-500)
    assert "gap_through_sl" in trade.metadata["exit_fill_flags"]


def test_sell_gap_through_stop_fills_at_the_ask_open():
    bars = frame([(1.1, 1.1001, 1.0999, 1.1, 10), (1.105, 1.1055, 1.1045, 1.105, 10)])
    trade = only_trade(run(bars, "SELL", 1.101, 1.098))
    assert trade.entry_price == 1.1  # a SELL opens on the bid
    assert trade.exit_reason == "SL"
    assert trade.exit_price == 1.1051  # bid open + 10 points
    assert trade.profit == pytest.approx(-510)


def test_gap_through_take_profit_fills_at_the_target_not_the_better_open():
    bars = frame([(1.1, 1.1002, 1.0999, 1.1, 0), (1.105, 1.106, 1.1045, 1.105, 0)])
    trade = only_trade(run(bars, "BUY", 1.099, 1.102))
    assert (trade.exit_reason, trade.exit_price) == ("TP", 1.102)


def test_gap_through_a_moved_break_even_stop_also_fills_at_the_open():
    bars = frame([(1.1, 1.1006, 1.0999, 1.1004, 0), (1.0995, 1.0997, 1.0993, 1.0996, 0)])
    trade = only_trade(run(bars, "BUY", 1.099, 1.105, break_even_trigger_r=0.5))
    assert trade.final_sl_price == 1.1
    assert (trade.exit_reason, trade.exit_price) == ("SL", 1.0995)
    assert trade.profit == pytest.approx(-50)


def test_sell_stop_triggers_when_the_ask_reaches_it():
    bars = frame([(1.1, 1.1, 1.1, 1.1, 10), (1.1, 1.10095, 1.0995, 1.1, 10), (1.1, 1.1, 1.1, 1.1, 10)])
    trade = only_trade(run(bars, "SELL", 1.101, 1.098))
    assert (trade.exit_reason, trade.exit_price) == ("SL", 1.101)
    assert trade.exit_time == bars.timestamp[1].isoformat()
    assert trade.mae == pytest.approx(-0.00105)  # entry bid 1.1 versus ask high 1.10105


def test_sell_target_needs_the_ask_not_the_bid():
    bars = frame([(1.1, 1.1, 1.1, 1.1, 10), (1.1, 1.1, 1.09795, 1.1, 10), (1.1, 1.1, 1.1, 1.1, 10)])
    trade = only_trade(run(bars, "SELL", 1.101, 1.098))
    assert trade.exit_reason == "END_OF_DATA"
    assert trade.exit_price == 1.1001  # closes on the ask


def test_buy_opens_on_the_ask_and_its_barriers_stay_on_the_bid():
    bars = frame([(1.1, 1.1, 1.1, 1.1, 20), (1.1, 1.10195, 1.0991, 1.1, 20), (1.1, 1.1, 1.1, 1.1, 20)])
    trade = only_trade(run(bars, "BUY", 1.099, 1.102))
    assert trade.entry_price == 1.1002
    assert (trade.exit_reason, trade.exit_price) == ("END_OF_DATA", 1.1)
    assert trade.profit == pytest.approx(-20)


def test_exit_spread_comes_from_the_exit_bar():
    bars = frame([(1.1, 1.1, 1.1, 1.1, 2), (1.1, 1.1, 1.1, 1.1, 20)])
    trade = only_trade(run(bars, "SELL", 1.101, 1.098))
    assert trade.spread_points == 2
    assert trade.metadata["exit_spread_points"] == 20
    assert trade.exit_price == 1.1002
    assert trade.profit == pytest.approx(-20)


def test_entry_spread_gate_never_refuses_a_protective_exit():
    bars = frame([(1.1, 1.1, 1.1, 1.1, 2), (1.1, 1.1, 1.1, 1.1, 40)])
    trade = only_trade(run(bars, "SELL", 1.101, 1.098))
    assert trade.exit_price == 1.1004
    blocked = run(frame([(1.1, 1.1, 1.1, 1.1, 40), (1.1, 1.1, 1.1, 1.1, 2)]), "SELL", 1.101, 1.098)
    assert blocked.trades == ()
    assert blocked.rejected_candidates[0]["reason"] == "spread exceeds configured maximum"


def test_missing_held_bar_spread_is_not_zero_but_the_widest_admitted():
    bars = frame([(1.1, 1.1, 1.1, 1.1, 2), (1.1, 1.1, 1.1, 1.1, float("nan"))])
    trade = only_trade(run(bars, "SELL", 1.101, 1.098))
    assert trade.metadata["exit_spread_points"] == 25
    assert trade.metadata["assumed_spread_bars"] == 1
    assert trade.exit_price == 1.10025


def _trade_rows(profits):
    return [{"profit": profit, "r_multiple": profit / 100.0, "signal_id": str(index),
             "entry_time": f"2026-01-{index + 5:02d}T00:00:00Z", "exit_time": f"2026-01-{index + 5:02d}T01:00:00Z"}
            for index, profit in enumerate(profits)]


def test_per_trade_statistic_is_reported_as_t_stat_not_sharpe():
    profits = [100.0, -50.0, 80.0, -20.0, 60.0]
    metrics = bt.calculate_metrics(_trade_rows(profits), initial_balance=10_000)
    equity = 10_000 + np.concatenate(([0.0], np.cumsum(profits)[:-1]))
    returns = np.array(profits) / equity
    assert metrics.t_stat == pytest.approx(returns.mean() / returns.std(ddof=1) * math.sqrt(len(returns)))
    # Without marks there is no daily mark-to-market equity, so no Sharpe is invented.
    assert metrics.sharpe is None
    payload = metrics.to_project_result(run_id="r")
    assert payload["t_stat"] == metrics.t_stat and payload["sharpe"] is None


def test_sharpe_is_annualised_from_daily_mark_to_market_equity_with_flat_days():
    closes = [1.101, 1.099, 1.102, 1.103, 1.103, 1.103, 1.103, 1.103, 1.103, 1.103]
    bars = frame([(1.1 if i == 0 else closes[i - 1], 1.104, 1.0995, close, 0) for i, close in enumerate(closes)],
                 freq="B")
    outcome = run(bars, "BUY", 1.09, 1.11, max_bars_in_trade=4)
    trade = only_trade(outcome)
    assert trade.exit_reason == "END_OF_DATA" and trade.profit == pytest.approx(300)
    # The open trade is marked at every close; the six flat days are kept.
    daily = np.array([10_100, 9_900, 10_200, 10_300, 10_300, 10_300, 10_300, 10_300, 10_300, 10_300], dtype=float)
    returns = daily / np.concatenate(([10_000.0], daily[:-1])) - 1.0
    metrics = outcome.metrics
    assert metrics.sharpe == pytest.approx(returns.mean() / returns.std(ddof=1) * math.sqrt(WEEKDAYS_PER_YEAR))
    centred = returns - returns.mean()
    scale = math.sqrt(np.mean(centred**2))
    assert metrics.skew == pytest.approx(np.mean(centred**3) / scale**3)
    assert metrics.kurtosis == pytest.approx(np.mean(centred**4) / scale**4)
    cagr = (10_300 / 10_000) ** (WEEKDAYS_PER_YEAR / len(returns)) - 1.0
    assert metrics.cagr_pct == pytest.approx(cagr * 100.0)
    assert metrics.calmar == pytest.approx(cagr / (200 / 10_100))
    # The old per-trade statistic is undefined for one trade; it is not the Sharpe.
    assert metrics.t_stat is None
    curve = outcome.mark_to_market_curve
    assert list(curve["equity"]) == pytest.approx(list(daily))


def test_daily_sharpe_does_not_grow_with_the_number_of_trades():
    # The same daily pattern observed for ten times longer: a ratio estimate is
    # unchanged, the t-statistic grows by sqrt(10).
    profits = np.tile([100.0, -50.0, 80.0, -20.0, 60.0], 800)
    stamps = pd.bdate_range("2010-01-04", periods=len(profits), tz="UTC")
    rows = [{"profit": p, "r_multiple": p / 100.0, "signal_id": str(i), "entry_time": t, "exit_time": t}
            for i, (p, t) in enumerate(zip(profits, stamps))]
    marks = pd.DataFrame({"timestamp": stamps, "equity": 1_000_000.0 + np.cumsum(profits)})
    small = bt.calculate_metrics(rows[:400], initial_balance=1_000_000, mark_to_market=marks.iloc[:400])
    large = bt.calculate_metrics(rows, initial_balance=1_000_000, mark_to_market=marks)
    assert large.t_stat / small.t_stat == pytest.approx(math.sqrt(10), rel=0.02)
    assert large.sharpe == pytest.approx(small.sharpe, rel=0.02)


def test_weekend_marks_roll_into_monday():
    marks = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-09T20:00Z", "2026-01-11T22:00Z", "2026-01-12T20:00Z"]),
        "equity": [10_000.0, 10_050.0, 10_100.0],
    })
    daily = bt._daily_mark_to_market_equity(marks)
    assert list(daily.index.strftime("%Y-%m-%d")) == ["2026-01-09", "2026-01-12"]
    assert list(daily) == [10_000.0, 10_100.0]


def test_batch_summary_and_engine_version_expose_both_statistics(tmp_path):
    from test_backtesting import _historical_csv

    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    _historical_csv(data_dir / "EURUSD_M5.csv", rows=260)
    summary = bt.run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD",)).summary
    assert {"t_stat", "sharpe", "skew", "kurtosis", "cagr_pct", "calmar"} <= set(summary)
    assert bt.ENGINE_VERSION == "0.4.0"


def test_readers_keep_the_daily_sharpe_and_the_t_stat_apart(tmp_path):
    from agi_style_forex_bot_mt5.benchmarks.benchmark_runner import _metrics_row
    from agi_style_forex_bot_mt5.benchmarks.competitive_scorecard import build_competitive_scorecard

    metrics = bt.calculate_metrics(_trade_rows([100.0, -50.0, 80.0]), initial_balance=10_000)
    row = _metrics_row("EURUSD", "S", metrics, status="OK")
    assert (row["sharpe"], row["t_stat"]) == (None, metrics.t_stat)
    (tmp_path / "backtests").mkdir()
    (tmp_path / "backtests" / "summary.json").write_text('{"sharpe": 0.8, "t_stat": 4.2}', encoding="utf-8")
    card = build_competitive_scorecard(reports_root=tmp_path, output_dir=tmp_path / "out")["scorecard"]
    assert (card["sharpe"], card["t_stat"]) == (0.8, 4.2)
