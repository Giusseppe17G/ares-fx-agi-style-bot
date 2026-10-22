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


REJECTED = ("stop_move_rejected_invalid_side",)


def test_gap_through_a_moved_break_even_stop_also_fills_at_the_open():
    # The 1.1004 bid close is above the 1.1000 break-even stop, so the move is
    # valid; bar 2 then opens below it.
    bars = frame([(1.1, 1.1006, 1.0999, 1.1004, 0), (1.0995, 1.0997, 1.0993, 1.0996, 0)])
    trade = only_trade(run(bars, "BUY", 1.099, 1.105, break_even_trigger_r=0.5))
    assert trade.final_sl_price == 1.1
    assert (trade.exit_reason, trade.exit_price) == ("SL", 1.0995)
    assert trade.metadata["exit_fill_flags"] == ("gap_through_sl",)
    assert (trade.metadata["stop_move_flags"], trade.metadata["stop_moves_rejected"]) == ((), 0)
    assert trade.profit == pytest.approx(-50)


@pytest.mark.parametrize("direction,rows,sl,tp,management,exit_reason,exit_price,profit,rejections", [
    # Trigger 0R, lock 10: the 1.1001 proposal is above the 1.10005 bid high and the 1.0998 close.
    ("BUY", [(1.1, 1.10005, 1.0995, 1.0998, 0), (1.0998, 1.0999, 1.099, 1.0995, 0), (1.0995, 1.0996, 1.0994, 1.0995, 0)],
     1.099, 1.11, {"break_even_trigger_r": 0.0, "break_even_lock_points": 10}, "SL", 1.099, -100, 1),
    # 0.5R with a 60-point lock: the 1.1006 proposal is above the 1.1005 high; re-proposed at every close.
    ("BUY", [(1.1, 1.1005, 1.0999, 1.1003, 0), (1.1003, 1.1004, 1.0992, 1.0995, 0), (1.0995, 1.0996, 1.0994, 1.0995, 0)],
     1.099, 1.11, {"break_even_trigger_r": 0.5, "break_even_lock_points": 60}, "END_OF_DATA", 1.0995, -50, 3),
    # Lock 0 with a 20-point spread: the stop would be the 1.1002 ask entry; the bid never exceeds 1.1001.
    ("BUY", [(1.1, 1.1001, 1.0995, 1.1, 20), (1.1, 1.1001, 1.099, 1.0995, 20), (1.0995, 1.0996, 1.0994, 1.0995, 20)],
     1.098, 1.11, {"break_even_trigger_r": 0.0}, "END_OF_DATA", 1.0995, -70, 3),
    # SELL on the ask: the 1.0999 proposal is below the 1.1002 ask close.
    ("SELL", [(1.1, 1.1005, 1.09995, 1.1002, 0), (1.1002, 1.101, 1.1001, 1.1005, 0), (1.1005, 1.1006, 1.1004, 1.1005, 0)],
     1.101, 1.09, {"break_even_trigger_r": 0.0, "break_even_lock_points": 10}, "SL", 1.101, -100, 1),
    # The next bar opens above the never-touched 1.1006 proposal and runs to the target.
    ("BUY", [(1.1, 1.1005, 1.0999, 1.1003, 0), (1.101, 1.11, 1.1008, 1.109, 0), (1.109, 1.1096, 1.1084, 1.1095, 0)],
     1.099, 1.11, {"break_even_trigger_r": 0.5, "break_even_lock_points": 60}, "TP", 1.11, 1000, 1),
])
def test_break_even_beyond_the_closing_quote_is_rejected_and_the_old_stop_stays(
        direction, rows, sl, tp, management, exit_reason, exit_price, profit, rejections):
    # At the bar close MT5 refuses an SL at or beyond the bid (BUY) or ask (SELL):
    # the stop in force is unchanged, so no exit can fill at the untraded proposal.
    trade = only_trade(run(frame(rows), direction, sl, tp, **management))
    assert trade.final_sl_price == sl
    assert (trade.exit_reason, trade.exit_price) == (exit_reason, exit_price)
    assert trade.metadata["exit_fill_flags"] == ()
    assert trade.metadata["stop_move_flags"] == REJECTED
    assert trade.metadata["stop_moves_rejected"] == rejections
    assert trade.profit == pytest.approx(profit)


def test_a_real_gap_through_the_stop_kept_after_a_rejected_move_fills_at_the_open():
    bars = frame([(1.1, 1.10005, 1.0995, 1.0998, 0), (1.0985, 1.0987, 1.098, 1.0985, 0)])
    trade = only_trade(run(bars, "BUY", 1.099, 1.11, break_even_trigger_r=0.0, break_even_lock_points=10))
    assert trade.final_sl_price == 1.099
    assert (trade.exit_reason, trade.exit_price) == ("SL", 1.0985)
    assert trade.metadata["exit_fill_flags"] == ("gap_through_sl",)
    assert trade.metadata["stop_move_flags"] == REJECTED
    assert trade.profit == pytest.approx(-150)


@pytest.mark.parametrize("direction,rows,sl,tp,distance,exit_price,profit,rejections", [
    # Bar 1 peaks at 1.1030 and closes at 1.1015: the 1.1029 trail is behind the
    # bid close, as is bar 2's 1.1015. Bar 2 trades below 1.1029 without an exit
    # and bar 3 reaches the 1.0980 stop still in force.
    ("BUY", [(1.1, 1.1, 1.1, 1.1, 0), (1.1, 1.103, 1.1, 1.1015, 0), (1.1015, 1.1016, 1.1005, 1.1006, 0),
             (1.1006, 1.1006, 1.0975, 1.0978, 0)], 1.098, 1.11, 10, 1.098, -200, 2),
    # Ask low 1.0986 trails to 1.0989, below the 1.0991 ask close; bar 2's ask high reaches 1.1020.
    ("SELL", [(1.1, 1.1, 1.1, 1.1, 10), (1.0995, 1.0995, 1.0985, 1.099, 10), (1.099, 1.1025, 1.0989, 1.102, 10)],
     1.102, 1.09, 30, 1.102, -200, 1),
])
def test_trailing_stop_that_would_land_behind_the_close_is_rejected(
        direction, rows, sl, tp, distance, exit_price, profit, rejections):
    bars = frame(rows)
    trade = only_trade(run(bars, direction, sl, tp, trailing_start_r=0.5, trailing_distance_points=distance))
    assert trade.final_sl_price == sl
    assert (trade.exit_reason, trade.exit_price) == ("SL", exit_price)
    assert trade.exit_time == bars.timestamp[len(rows) - 1].isoformat()
    assert trade.metadata["exit_fill_flags"] == ()
    assert (trade.metadata["stop_move_flags"], trade.metadata["stop_moves_rejected"]) == (REJECTED, rejections)
    assert trade.profit == pytest.approx(profit)


def test_a_refused_break_even_plus_trailing_move_keeps_the_whole_previous_stop():
    # One modification per close: break-even alone (1.1000) would be valid, but
    # the 1.1029 trail sent with it is behind the 1.1015 close, so MT5 refuses
    # the whole request and the initial stop stays.
    bars = frame([(1.1, 1.1, 1.1, 1.1, 0), (1.1, 1.103, 1.1, 1.1015, 0)])
    trade = only_trade(run(bars, "BUY", 1.098, 1.11, break_even_trigger_r=0.5,
                           trailing_start_r=0.5, trailing_distance_points=10))
    assert trade.final_sl_price == 1.098
    assert (trade.metadata["stop_move_flags"], trade.metadata["stop_moves_rejected"]) == (REJECTED, 1)


@pytest.mark.parametrize("direction,bar1,sl,tp,final_sl,flags", [
    # The 1.1029 trail equal to the bid close is not strictly below it; one tick above it is.
    ("BUY", (1.1, 1.103, 1.1, 1.1029, 0), 1.098, 1.11, 1.098, REJECTED),
    ("BUY", (1.1, 1.103, 1.1, 1.10291, 0), 1.098, 1.11, 1.1029, ()),
    ("SELL", (1.1, 1.1, 1.097, 1.0971, 0), 1.102, 1.09, 1.102, REJECTED),
    ("SELL", (1.1, 1.1, 1.097, 1.09709, 0), 1.102, 1.09, 1.0971, ()),
])
def test_moved_stop_must_be_strictly_on_the_protective_side_of_the_close(direction, bar1, sl, tp, final_sl, flags):
    bars = frame([(1.1, 1.1, 1.1, 1.1, 0), bar1])
    trade = only_trade(run(bars, direction, sl, tp, trailing_start_r=0.5, trailing_distance_points=10))
    assert trade.final_sl_price == final_sl
    assert trade.metadata["stop_move_flags"] == flags


@pytest.mark.parametrize("slippage,entry,exit_price,profit", [(0, 1.1, 1.1029, 290), (2, 1.10002, 1.10288, 286)])
def test_a_valid_trailing_move_applies_from_the_next_bar(slippage, entry, exit_price, profit):
    # Bar 1 trades down to 1.0995 but the 1.1029 trail only comes into force at
    # its 1.1030 close; bar 2 reaches it without a gap.
    bars = frame([(1.1, 1.1, 1.1, 1.1, 0), (1.1, 1.103, 1.0995, 1.103, 0), (1.103, 1.1032, 1.1025, 1.1027, 0),
                  (1.1027, 1.1027, 1.1027, 1.1027, 0)])
    trade = only_trade(run(bars, "BUY", 1.098, 1.11, trailing_start_r=0.5, trailing_distance_points=10,
                           cost_model=CostModel(slippage_points=slippage, max_spread_points=25)))
    assert trade.entry_price == entry
    assert trade.final_sl_price == 1.1029
    assert (trade.exit_reason, trade.exit_price) == ("SL", exit_price)
    assert trade.exit_time == bars.timestamp[2].isoformat()
    assert trade.metadata["exit_fill_flags"] == ()
    assert trade.metadata["stop_move_flags"] == ()
    assert trade.profit == pytest.approx(profit)


def test_a_real_gap_through_a_trailed_stop_still_fills_at_the_open():
    # Bar 1 closes at 1.1030, above the 1.1029 trailed stop; bar 2 gaps to 1.1020.
    bars = frame([(1.1, 1.1, 1.1, 1.1, 0), (1.1, 1.103, 1.1, 1.103, 0), (1.102, 1.1022, 1.1018, 1.102, 0)])
    trade = only_trade(run(bars, "BUY", 1.098, 1.11, trailing_start_r=0.5, trailing_distance_points=10))
    assert trade.final_sl_price == 1.1029
    assert (trade.exit_reason, trade.exit_price) == ("SL", 1.102)
    assert trade.metadata["exit_fill_flags"] == ("gap_through_sl",)
    assert trade.metadata["stop_move_flags"] == ()
    assert trade.profit == pytest.approx(200)


@pytest.mark.parametrize("direction,rows,sl,tp,exit_price,profit", [
    # Reviewer case: 6214fec ended this at the close with final_sl 1.1029, a stop
    # the close had already crossed. Under bar-close management the trail was
    # refused, so the 1.0980 stop was in force and END_OF_DATA is the true label.
    ("BUY", [(1.1, 1.1, 1.1, 1.1, 0), (1.1, 1.103, 1.1, 1.1015, 0)], 1.098, 1.11, 1.1015, 150),
    ("SELL", [(1.1, 1.1, 1.1, 1.1, 0), (1.1, 1.1, 1.097, 1.0985, 0)], 1.102, 1.09, 1.0985, 150),
])
def test_last_bar_close_behind_a_proposed_stop_is_end_of_data_with_the_stop_in_force(
        direction, rows, sl, tp, exit_price, profit):
    trade = only_trade(run(frame(rows), direction, sl, tp, trailing_start_r=0.5, trailing_distance_points=10))
    assert (trade.exit_reason, trade.exit_price) == ("END_OF_DATA", exit_price)
    assert trade.final_sl_price == sl
    # The reported stop is on the safe side of the close the trade ended at.
    assert trade.final_sl_price < exit_price if direction == "BUY" else trade.final_sl_price > exit_price
    assert trade.metadata["stop_move_flags"] == REJECTED
    assert trade.profit == pytest.approx(profit)


def _continuous_walk(count, seed, spread=10):
    """Random-walk bid bars whose open is the previous close: no gap anywhere."""
    rng = np.random.default_rng(seed)
    close = 1.1 + np.cumsum(rng.normal(0.0, 0.0004, count))
    opens = np.concatenate(([1.1], close[:-1]))
    wick = np.abs(rng.normal(0.0, 0.0003, (2, count)))
    rows = zip(np.round(opens, 5), np.round(np.maximum(opens, close) + wick[0], 5),
               np.round(np.minimum(opens, close) - wick[1], 5), np.round(close, 5), [spread] * count)
    return frame(list(rows))


@pytest.mark.parametrize("management", [
    {"break_even_trigger_r": 0.0, "break_even_lock_points": 30},
    {"break_even_trigger_r": 0.2, "break_even_lock_points": 60, "trailing_start_r": 0.3, "trailing_distance_points": 15},
    {"trailing_start_r": 0.0, "trailing_distance_points": 5},
])
def test_moved_stops_never_fill_at_a_price_the_exit_bar_did_not_trade(management):
    bars = _continuous_walk(2000, seed=7)
    candidates = []
    for index in range(0, len(bars) - 60, 40):
        bid = float(bars.open[index])
        direction = "BUY" if index % 80 else "SELL"
        sign = 1 if direction == "BUY" else -1
        candidates.append(TradeCandidate(
            timestamp=bars.timestamp[index], symbol="EURUSD", direction=direction, lot=1.0, signal_id=str(index),
            sl_price=round(bid - sign * 0.0025 + (0.0001 if direction == "SELL" else 0), 5),
            tp_price=round(bid + sign * 0.005, 5)))
    settings = BacktestSettings(cost_model=CostModel(max_spread_points=25), max_bars_in_trade=50, **management)
    outcome = Backtester(settings).run(bars, candidates)
    assert outcome.rejected_candidates == () and len(outcome.trades) == len(candidates)
    by_time = bars.set_index(bars.timestamp.map(pd.Timestamp.isoformat))
    for trade in outcome.trades:
        bar = by_time.loc[trade.exit_time]
        offset = 0.0 if trade.direction == "BUY" else 10 * POINT  # SELL closes on the ask
        assert bar.low + offset - 1e-9 <= trade.exit_price <= bar.high + offset + 1e-9, trade
        assert "moved_stop_crossed_in_prior_bar" not in trade.metadata["exit_fill_flags"]
        assert "gap_through_sl" not in trade.metadata["exit_fill_flags"]
    # Both paths are exercised: refused proposals and stops that did move.
    assert any(trade.metadata["stop_moves_rejected"] for trade in outcome.trades)
    assert any(trade.final_sl_price != trade.initial_sl_price for trade in outcome.trades)


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


def test_sell_trailing_stop_follows_and_triggers_on_the_ask():
    # Ask low 1.0986 (bid 1.0985 + 10 points) trails the stop to 1.0989, not
    # 1.0988; it is above the 1.0987 ask close, so the move is valid. Bar 2's
    # ask high 1.0989 (bid 1.0988) reaches it.
    bars = frame([(1.1, 1.1, 1.1, 1.1, 10), (1.0995, 1.0995, 1.0985, 1.0986, 10),
                  (1.0986, 1.0988, 1.0984, 1.0987, 10)])
    trade = only_trade(run(bars, "SELL", 1.102, 1.09, trailing_start_r=0.5, trailing_distance_points=30))
    assert trade.final_sl_price == 1.0989
    assert (trade.exit_reason, trade.exit_price) == ("SL", 1.0989)
    assert trade.metadata["exit_fill_flags"] == ()
    assert trade.metadata["stop_move_flags"] == ()
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


DAILY_METRICS = ("sharpe", "skew", "kurtosis", "cagr_pct", "calmar")


def assert_every_missing_daily_metric_has_a_reason(daily):
    """Each None daily metric is explained by a flag whose scope names it."""
    values = daily if isinstance(daily, dict) else {name: getattr(daily, name) for name in DAILY_METRICS}
    flags = values["daily_metrics_flags"] if isinstance(daily, dict) else daily.daily_metrics_flags
    assert set(flags) <= set(bt.DAILY_METRIC_FLAG_SCOPE), flags
    explained = {metric for flag in flags for metric in bt.DAILY_METRIC_FLAG_SCOPE[flag]}
    missing = {name for name in DAILY_METRICS if values[name] is None}
    assert missing <= explained, (missing, flags)
    # A flag never sits beside a value it claims is missing.
    assert not explained & {name for name in DAILY_METRICS if values[name] is not None}, (values, flags)


def test_two_weekdays_of_marks_report_no_sharpe_cagr_or_calmar():
    # Without the guard: Sharpe 5.84, CAGR 1224% and Calmar 1261 from two days.
    metrics = bt.calculate_metrics([], initial_balance=10_000, mark_to_market=_marks([10_300, 10_200]))
    assert (metrics.sharpe, metrics.cagr_pct, metrics.calmar) == (None, None, None)
    assert (metrics.skew, metrics.kurtosis) == (None, None)
    assert metrics.daily_returns_count == 2
    assert metrics.daily_metrics_flags == (bt.INSUFFICIENT_DAILY_SAMPLE_SHARPE, bt.INSUFFICIENT_DAILY_SAMPLE_MOMENTS,
                                           bt.INSUFFICIENT_DAILY_SAMPLE_CAGR_CALMAR)
    assert_every_missing_daily_metric_has_a_reason(metrics)
    payload = metrics.to_project_result(run_id="r")
    assert payload["daily_returns_count"] == 2
    assert json.loads(payload["daily_metrics_flags_json"]) == list(metrics.daily_metrics_flags)


def test_daily_sample_thresholds_are_one_month_for_sharpe_and_one_year_for_growth():
    assert (bt.MIN_DAILY_RETURNS_SHARPE, bt.MIN_DAILY_RETURNS_ANNUALISED) == (20, 261)
    assert bt.MIN_DAILY_RETURNS_MOMENTS == 20
    pattern = [10_000 + (50 if i % 2 else -30) + 2 * i for i in range(300)]
    below = bt.calculate_metrics([], initial_balance=10_000, mark_to_market=_marks(pattern[:19]))
    assert below.sharpe is None and bt.INSUFFICIENT_DAILY_SAMPLE_SHARPE in below.daily_metrics_flags
    # Skew and kurtosis no longer come from as few as 3 daily returns.
    assert (below.skew, below.kurtosis) == (None, None)
    assert bt.INSUFFICIENT_DAILY_SAMPLE_MOMENTS in below.daily_metrics_flags
    assert_every_missing_daily_metric_has_a_reason(below)
    at = bt.calculate_metrics([], initial_balance=10_000, mark_to_market=_marks(pattern[:20]))
    assert at.sharpe == pytest.approx(_sharpe(np.array(pattern[:20], dtype=float))[1])
    assert at.skew is not None and at.kurtosis is not None
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
    assert_every_missing_daily_metric_has_a_reason(metrics)


@pytest.mark.parametrize("days,flags,cagr_pct", [
    (25, ("DAILY_RETURNS_ZERO_VARIANCE", "INSUFFICIENT_DAILY_SAMPLE_CAGR_CALMAR"), None),
    # A flat year has a CAGR of 0 but no drawdown to divide by.
    (261, ("DAILY_RETURNS_ZERO_VARIANCE", "CALMAR_ZERO_DRAWDOWN"), 0.0),
])
def test_flat_equity_flags_zero_variance_and_zero_drawdown(days, flags, cagr_pct):
    metrics = bt.calculate_metrics([], initial_balance=10_000, mark_to_market=_marks([10_000] * days))
    assert (metrics.sharpe, metrics.skew, metrics.kurtosis, metrics.calmar) == (None, None, None, None)
    assert metrics.cagr_pct == cagr_pct
    assert metrics.daily_metrics_flags == flags
    assert_every_missing_daily_metric_has_a_reason(metrics)


def test_a_year_without_drawdown_flags_the_missing_calmar():
    metrics = bt.calculate_metrics([], initial_balance=10_000,
                                   mark_to_market=_marks([10_000 + 10 * (i + 1) for i in range(261)]))
    assert metrics.sharpe is not None and metrics.cagr_pct is not None
    assert metrics.calmar is None
    assert metrics.daily_metrics_flags == (bt.CALMAR_ZERO_DRAWDOWN,)
    assert_every_missing_daily_metric_has_a_reason(metrics)


def test_unrepresentable_growth_flags_the_missing_cagr_and_calmar():
    # Each daily ratio is finite; the year's growth (1e310) is not.
    equity = pd.Series(np.logspace(-10, 300, 262)[1:])
    daily = bt._daily_equity_metrics(equity, 1e-10)
    assert (daily["cagr_pct"], daily["calmar"]) == (None, None)
    assert bt.CAGR_OVERFLOW in daily["daily_metrics_flags"]
    assert_every_missing_daily_metric_has_a_reason(daily)


@pytest.mark.parametrize("level,initial", [
    (1e10, 1e-300),  # the first daily return overflows to inf
    (1e100, 1.0),  # a finite return whose fourth moment overflows (it used to raise OverflowError)
    (1e160, 1.0),  # a finite return whose variance overflows
])
def test_unrepresentable_daily_returns_flag_the_missing_ratios(level, initial):
    with np.errstate(over="raise", invalid="raise"):  # no overflow escapes the guarded block
        daily = bt._daily_equity_metrics(pd.Series([level] * 25), initial)
    assert (daily["sharpe"], daily["skew"], daily["kurtosis"]) == (None, None, None)
    assert daily["daily_metrics_flags"] == (bt.DAILY_RETURNS_NOT_FINITE, bt.INSUFFICIENT_DAILY_SAMPLE_CAGR_CALMAR)
    assert_every_missing_daily_metric_has_a_reason(daily)


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
    # 0.4.1: break-even/trailing moves behind the closing quote are refused.
    assert bt.ENGINE_VERSION == "0.4.1"


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
