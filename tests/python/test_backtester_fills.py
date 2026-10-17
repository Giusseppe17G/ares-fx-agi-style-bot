"""Bid-bar exit fills, gaps, exit-bar spread and daily metrics; synthetic, no broker."""

import json
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


@pytest.mark.parametrize("next_open", [1.1015, 1.1031])
def test_stop_trailed_behind_the_bar_close_fills_at_the_stop_not_as_a_gap(next_open):
    # Bar 1 peaks at 1.1030 and closes at 1.1015, through the 1.1029 stop trailed
    # from that peak: the price crossed it inside bar 1. Bar 2's open is neither a
    # gap (1.1015) nor a reason to keep the trade alive (1.1031).
    bars = frame([(1.1, 1.1, 1.1, 1.1, 0), (1.1, 1.103, 1.1, 1.1015, 0),
                  (next_open, next_open + 0.0004, next_open - 0.0005, next_open, 0), (1.1012, 1.1012, 1.1012, 1.1012, 0)])
    trade = only_trade(run(bars, "BUY", 1.098, 1.11, trailing_start_r=0.5, trailing_distance_points=10))
    assert trade.final_sl_price == 1.1029
    assert (trade.exit_reason, trade.exit_price) == ("SL", 1.1029)
    assert trade.exit_time == bars.timestamp[2].isoformat()
    assert trade.metadata["exit_fill_flags"] == ("moved_stop_crossed_in_prior_bar",)
    assert trade.profit == pytest.approx(290)


def test_stop_level_after_a_prior_bar_crossing_still_pays_slippage():
    bars = frame([(1.1, 1.1, 1.1, 1.1, 0), (1.1, 1.103, 1.1, 1.1015, 0), (1.1015, 1.1018, 1.101, 1.1012, 0)])
    trade = only_trade(run(bars, "BUY", 1.098, 1.11, trailing_start_r=0.5, trailing_distance_points=10,
                           cost_model=CostModel(slippage_points=2, max_spread_points=25)))
    assert trade.entry_price == 1.10002
    assert trade.exit_price == 1.10288  # the 1.1029 stop minus 2 points
    assert "gap_through_sl" not in trade.metadata["exit_fill_flags"]


def test_a_real_gap_through_a_trailed_stop_still_fills_at_the_open():
    # Bar 1 closes at 1.1030, above the 1.1029 trailed stop; bar 2 gaps to 1.1020.
    bars = frame([(1.1, 1.1, 1.1, 1.1, 0), (1.1, 1.103, 1.1, 1.103, 0), (1.102, 1.1022, 1.1018, 1.102, 0)])
    trade = only_trade(run(bars, "BUY", 1.098, 1.11, trailing_start_r=0.5, trailing_distance_points=10))
    assert trade.final_sl_price == 1.1029
    assert (trade.exit_reason, trade.exit_price) == ("SL", 1.102)
    assert trade.metadata["exit_fill_flags"] == ("gap_through_sl",)
    assert trade.profit == pytest.approx(200)


@pytest.mark.parametrize("direction,sl,tp,reason", [
    ("BUY", 1.1001, 1.11, "BUY candidate requires sl < bid < tp at entry"),  # between bid 1.1 and ask 1.1002
    ("BUY", 1.1, 1.11, "BUY candidate requires sl < bid < tp at entry"),  # at the bid: an instant stop
    ("SELL", 1.1001, 1.09, "SELL candidate requires tp < ask < sl at entry"),  # between bid 1.1 and ask 1.1002
    ("SELL", 1.1002, 1.09, "SELL candidate requires tp < ask < sl at entry"),  # at the ask: an instant stop
])
def test_protection_already_crossed_on_its_trigger_side_is_rejected(direction, sl, tp, reason):
    bars = frame([(1.1, 1.1, 1.1, 1.1, 20), (1.1, 1.1, 1.1, 1.1, 20)])
    outcome = run(bars, direction, sl, tp)
    assert outcome.trades == ()
    assert outcome.rejected_candidates[0]["reason"] == reason
    assert bt._canonical_trade_blocker(reason) == "INVALID_RR"


@pytest.mark.parametrize("direction,sl,tp", [("BUY", 1.09999, 1.11), ("SELL", 1.10021, 1.09)])
def test_protection_one_tick_beyond_its_trigger_quote_is_accepted(direction, sl, tp):
    bars = frame([(1.1, 1.1, 1.1, 1.1, 20), (1.1, 1.1, 1.1, 1.1, 20)])
    trade = only_trade(run(bars, direction, sl, tp))
    assert trade.exit_reason == "END_OF_DATA"


@pytest.mark.parametrize("bid_low,moved", [(1.099, False), (1.0989, True)])
def test_sell_break_even_is_measured_on_the_ask(bid_low, moved):
    # Entry bid 1.1, ask = bid + 10 points. 0.5R is 10 pips of ask move: the
    # 1.0990 bid low (ask 1.0991) is one point short; 1.0989 (ask 1.0990) is not.
    bars = frame([(1.1, 1.1, 1.1, 1.1, 10), (1.0995, 1.0995, bid_low, 1.0992, 10),
                  (1.0993, 1.0999, 1.0992, 1.0993, 10)])
    trade = only_trade(run(bars, "SELL", 1.102, 1.09, break_even_trigger_r=0.5))
    if moved:
        assert trade.final_sl_price == 1.1
        assert (trade.exit_reason, trade.exit_price) == ("SL", 1.1)  # bar 2's ask high 1.1000 reaches it
        assert trade.profit == pytest.approx(0)
    else:
        assert trade.final_sl_price == 1.102
        assert (trade.exit_reason, trade.exit_price) == ("END_OF_DATA", 1.0994)


@pytest.mark.parametrize("bar1_close,bar2,flags", [
    # Ask close 1.0987 is safe; bar 2's ask high 1.0989 (bid 1.0988) reaches the stop.
    (1.0986, (1.0986, 1.0988, 1.0984, 1.0987, 10), ()),
    # Ask close 1.0991 is already behind the stop: filled there, not at bar 2's open.
    (1.099, (1.099, 1.0992, 1.0989, 1.099, 10), ("moved_stop_crossed_in_prior_bar",)),
])
def test_sell_trailing_stop_follows_and_triggers_on_the_ask(bar1_close, bar2, flags):
    # Ask low 1.0986 (bid 1.0985 + 10 points) trails the stop to 1.0989, not 1.0988.
    bars = frame([(1.1, 1.1, 1.1, 1.1, 10), (1.0995, 1.0995, 1.0985, bar1_close, 10), bar2])
    trade = only_trade(run(bars, "SELL", 1.102, 1.09, trailing_start_r=0.5, trailing_distance_points=30))
    assert trade.final_sl_price == 1.0989
    assert (trade.exit_reason, trade.exit_price) == ("SL", 1.0989)
    assert trade.metadata["exit_fill_flags"] == flags
    assert trade.profit == pytest.approx(110)


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


def _sharpe(daily, initial=10_000.0):
    returns = daily / np.concatenate(([initial], daily[:-1])) - 1.0
    return returns, returns.mean() / returns.std(ddof=1) * math.sqrt(WEEKDAYS_PER_YEAR)


def test_sharpe_is_annualised_from_daily_mark_to_market_equity_with_flat_days():
    closes = [1.101, 1.099, 1.102] + [1.103] * 22
    bars = frame([(1.1 if i == 0 else closes[i - 1], 1.104, 1.0995, close, 0) for i, close in enumerate(closes)],
                 freq="B")
    outcome = run(bars, "BUY", 1.09, 1.11, max_bars_in_trade=4)
    trade = only_trade(outcome)
    assert trade.exit_reason == "END_OF_DATA" and trade.profit == pytest.approx(300)
    # The open trade is marked at every close; the 21 flat days are kept.
    daily = np.array([10_100, 9_900, 10_200] + [10_300] * 22, dtype=float)
    returns, sharpe = _sharpe(daily)
    metrics = outcome.metrics
    assert metrics.daily_returns_count == 25
    assert metrics.sharpe == pytest.approx(sharpe)
    centred = returns - returns.mean()
    scale = math.sqrt(np.mean(centred**2))
    assert metrics.skew == pytest.approx(np.mean(centred**3) / scale**3)
    assert metrics.kurtosis == pytest.approx(np.mean(centred**4) / scale**4)
    # 25 weekdays are not a year: no annualised growth is extrapolated from them.
    assert (metrics.cagr_pct, metrics.calmar) == (None, None)
    assert metrics.daily_metrics_flags == (bt.INSUFFICIENT_DAILY_SAMPLE_CAGR_CALMAR,)
    # The old per-trade statistic is undefined for one trade; it is not the Sharpe.
    assert metrics.t_stat is None
    curve = outcome.mark_to_market_curve
    assert list(curve["equity"]) == pytest.approx(list(daily))


def _marks(equity, start="2026-01-05"):
    stamps = pd.bdate_range(start, periods=len(equity), tz="UTC") + pd.Timedelta(hours=20)
    return pd.DataFrame({"timestamp": stamps, "equity": np.asarray(equity, dtype=float)})


def test_two_weekdays_of_marks_report_no_sharpe_cagr_or_calmar():
    # Without the guard: Sharpe 5.84, CAGR 1224% and Calmar 1261 from two days.
    metrics = bt.calculate_metrics([], initial_balance=10_000, mark_to_market=_marks([10_300, 10_200]))
    assert (metrics.sharpe, metrics.cagr_pct, metrics.calmar) == (None, None, None)
    assert metrics.daily_returns_count == 2
    assert metrics.daily_metrics_flags == (bt.INSUFFICIENT_DAILY_SAMPLE_SHARPE, bt.INSUFFICIENT_DAILY_SAMPLE_CAGR_CALMAR)
    payload = metrics.to_project_result(run_id="r")
    assert payload["daily_returns_count"] == 2
    assert json.loads(payload["daily_metrics_flags_json"]) == list(metrics.daily_metrics_flags)


def test_daily_sample_thresholds_are_one_month_for_sharpe_and_one_year_for_growth():
    assert (bt.MIN_DAILY_RETURNS_SHARPE, bt.MIN_DAILY_RETURNS_ANNUALISED) == (20, 261)
    pattern = [10_000 + (50 if i % 2 else -30) + 2 * i for i in range(300)]
    below = bt.calculate_metrics([], initial_balance=10_000, mark_to_market=_marks(pattern[:19]))
    assert below.sharpe is None and bt.INSUFFICIENT_DAILY_SAMPLE_SHARPE in below.daily_metrics_flags
    at = bt.calculate_metrics([], initial_balance=10_000, mark_to_market=_marks(pattern[:20]))
    assert at.sharpe == pytest.approx(_sharpe(np.array(pattern[:20], dtype=float))[1])
    assert at.daily_metrics_flags == (bt.INSUFFICIENT_DAILY_SAMPLE_CAGR_CALMAR,)
    short_year = bt.calculate_metrics([], initial_balance=10_000, mark_to_market=_marks(pattern[:260]))
    assert (short_year.cagr_pct, short_year.calmar) == (None, None)
    year = bt.calculate_metrics([], initial_balance=10_000, mark_to_market=_marks(pattern[:261]))
    equity = np.array([10_000.0] + pattern[:261])
    cagr = (equity[-1] / equity[0]) ** (WEEKDAYS_PER_YEAR / 261) - 1.0
    peaks = np.maximum.accumulate(equity)
    assert year.cagr_pct == pytest.approx(cagr * 100.0)
    assert year.calmar == pytest.approx(cagr / np.max((peaks - equity) / peaks))
    assert year.daily_metrics_flags == ()


def test_metrics_without_marks_flag_the_missing_mark_to_market():
    metrics = bt.calculate_metrics(_trade_rows([100.0, -50.0, 80.0]), initial_balance=10_000)
    assert metrics.daily_returns_count == 0
    assert metrics.daily_metrics_flags == (bt.MARK_TO_MARKET_UNAVAILABLE,)


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
    assert {"t_stat", "sharpe", "skew", "kurtosis", "cagr_pct", "calmar",
            "daily_returns_count", "daily_metrics_flags"} <= set(summary)
    assert bt.ENGINE_VERSION == "0.4.0"


def test_two_symbol_summary_aggregates_the_mark_to_market_curves(tmp_path, monkeypatch):
    from test_backtesting import _historical_csv

    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    for symbol in ("EURUSD", "GBPUSD"):
        _historical_csv(data_dir / f"{symbol}_M5.csv", rows=260)
    # Controlled daily trades replace the strategy, so every summary value is known.
    eur = [1.101, 1.099, 1.102] + [1.103] * 22  # BUY from 1.1: +100, -100, +200, closes +300
    gbp = [1.199, 1.201, 1.198] + [1.1985] * 22  # SELL from 1.2: +100, -100, +200, closes +150
    scripted = {
        "EURUSD": (frame([(1.1 if i == 0 else eur[i - 1], 1.104, 1.0995, c, 0) for i, c in enumerate(eur)],
                         start="2026-01-05", freq="B"), "BUY", 1.09, 1.11),
        "GBPUSD": (frame([(1.2 if i == 0 else gbp[i - 1], 1.2015, 1.1975, c, 0) for i, c in enumerate(gbp)],
                         start="2026-01-07", freq="B"), "SELL", 1.21, 1.19),
    }

    def scripted_backtest(candles, *, symbol, settings, **_):
        bars, direction, sl, tp = scripted[symbol]
        candidate = TradeCandidate(timestamp=bars.timestamp[0], symbol=symbol, direction=direction,
                                   sl_price=sl, tp_price=tp, lot=1.0)
        return Backtester(BacktestSettings(initial_balance=settings.initial_balance, max_bars_in_trade=4,
                                           cost_model=CostModel(max_spread_points=25))).run(bars, [candidate])

    monkeypatch.setattr(bt, "run_strategy_backtest", scripted_backtest)
    summary = bt.run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD", "GBPUSD")).summary
    # GBPUSD starts two weekdays later and ends two later; each symbol carries its
    # own last equity forward and the shared capital is counted once.
    daily = np.array([10_100, 9_900, 10_300, 10_200, 10_500, 10_450] + [10_450] * 21, dtype=float)
    returns, sharpe = _sharpe(daily)
    assert summary["total_trades"] == 2
    assert summary["net_return_pct"] == pytest.approx(4.5)
    assert summary["daily_returns_count"] == 27
    assert summary["sharpe"] == pytest.approx(sharpe)
    centred = returns - returns.mean()
    assert summary["skew"] == pytest.approx(np.mean(centred**3) / math.sqrt(np.mean(centred**2)) ** 3)
    assert (summary["cagr_pct"], summary["calmar"]) == (None, None)
    assert summary["daily_metrics_flags"] == [bt.INSUFFICIENT_DAILY_SAMPLE_CAGR_CALMAR]


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
