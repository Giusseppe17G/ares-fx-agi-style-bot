"""Walk-forward evidence excludes warmup trades, boundaries, and reused tests."""

from dataclasses import replace
import json

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting import walk_forward_optimizer as wf
from agi_style_forex_bot_mt5.backtesting.backtester import (
    Backtester, BacktestOutcome, BacktestSettings, TradeCandidate,
    build_equity_curve, calculate_metrics,
)


def _bars(count=100, frequency="5min"):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=count, freq=frequency, tz="UTC"),
        "open": [1.1] * count, "high": [1.21] * count,
        "low": [1.09] * count, "close": [1.11] * count,
        "spread_points": [0.0] * count,
    })


def _trade(timestamp, *, profit=5.0, signal_id="valid"):
    frame = _bars(2)
    frame["timestamp"] = pd.date_range(timestamp, periods=2, freq="5min")
    result = Backtester().run(frame, [TradeCandidate(timestamp=timestamp, symbol="EURUSD", direction="BUY", sl_price=1.0, tp_price=1.2)]).trades[0]
    return replace(result, profit=profit, r_multiple=profit / 10, signal_id=signal_id)


def _outcome(trades, *, limit=None, forged=False):
    settings = BacktestSettings(max_bars_in_trade=limit)
    metrics = calculate_metrics(trades)
    if forged:
        metrics = replace(metrics, net_profit=1e9, expectancy=1e9, average_r=1e9)
    return BacktestOutcome(settings, metrics, tuple(trades), (),
                           pd.DataFrame({"timestamp": [pd.Timestamp("2099-01-01T00:00Z")], "equity": [1e9]}))


@pytest.mark.parametrize("step", (0, -1, 4))
def test_nonpositive_or_overlapping_test_step_rejected(step):
    with pytest.raises(ValueError):
        wf.WalkForwardOptimizer(train_size=10, validation_size=5, test_size=5, step_size=step)


@pytest.mark.parametrize("settings", (
    wf.WalkForwardSettings(step_days=0), wf.WalkForwardSettings(step_days=-1),
    wf.WalkForwardSettings(test_days=30, step_days=10),
    wf.WalkForwardSettings(window_mode="unknown"),
))
def test_calendar_configuration_rejects_unsafe_windows(settings):
    with pytest.raises(ValueError):
        wf._calendar_windows(_bars(200, "D"), settings)


@pytest.mark.parametrize("issue", ("duplicate", "nat"))
def test_split_rejects_ambiguous_timestamps(issue):
    bars = _bars()
    bars.loc[1, "timestamp"] = bars.iloc[0].timestamp if issue == "duplicate" else pd.NaT
    with pytest.raises(ValueError):
        wf.WalkForwardOptimizer(train_size=10, validation_size=5, test_size=5).run(bars, [{}], lambda *_: None)


def test_warmup_and_purged_boundary_never_enter_metrics_or_equity():
    seen = []

    def callback(frame, params):
        context = frame.attrs["walk_forward_context"]
        first, last = pd.Timestamp(context["evaluation_start_utc"]), pd.Timestamp(context["evaluation_end_utc"])
        seen.append((frame.copy(), context.copy()))
        valid = _trade(first, profit=5)
        crossing = replace(_trade(first, profit=10_000, signal_id="future"), exit_time=(last + pd.Timedelta(minutes=5)).isoformat())
        trades = [valid, crossing]
        if context["warmup_rows"]:
            trades.append(_trade(frame.iloc[0].timestamp, profit=20_000, signal_id="warmup"))
        return _outcome(trades, forged=True)

    optimizer = wf.WalkForwardOptimizer(train_size=20, validation_size=10, test_size=10,
                                         warmup_size=4, purge_size=2, initial_balance=2_000)
    result = optimizer.run(_bars(40), [{}], callback)
    fold = result.folds[0]
    assert fold.train_metrics.net_profit == 5
    assert fold.validation_metrics.net_profit == 5
    assert fold.test_metrics.net_profit == 5
    assert fold.test_metrics.total_return_pct == pytest.approx(0.25)
    assert result.aggregate_test_metrics.net_profit == 5
    assert fold.temporal_audit["validation"]["purged_outcomes"] == {"WF_CROSS_BOUNDARY": 1, "WF_WARMUP_ENTRY": 1}
    for frame, context in seen:
        assert frame.iloc[-1].timestamp == pd.Timestamp(context["evaluation_end_utc"])
        assert len(frame) == context["warmup_rows"] + context["evaluation_rows"]


def test_first_validation_indicator_has_prior_history_without_future_rows():
    bars = _bars(40)
    bars["close"] = [1.0 + index / 1000 for index in range(40)]
    contexts = []

    def callback(frame, params):
        context = frame.attrs["walk_forward_context"]
        if context["stage"] == "validation":
            first = pd.Timestamp(context["evaluation_start_utc"])
            computed = frame.set_index("timestamp").close.rolling(4).mean().loc[first]
            expected = bars.loc[bars.timestamp <= first].close.tail(4).mean()
            assert computed == pytest.approx(expected)
            assert len(frame.loc[frame.timestamp < first]) == 4
            assert frame.timestamp.max() < bars.iloc[30].timestamp
            contexts.append(context)
        return _outcome([])

    wf.WalkForwardOptimizer(train_size=20, validation_size=10, test_size=10,
                             warmup_size=4, purge_size=1).run(bars, [{}], callback)
    assert len(contexts) == 1


def test_scoped_outcome_discards_truncated_closures_and_rebuilds_equity():
    frame = wf._window_input(_bars(20), 5, 20, stage="test", warmup=5, purge=2, initial_balance=500)
    start = pd.Timestamp(frame.attrs["walk_forward_context"]["evaluation_start_utc"])
    valid = _trade(start, profit=-10)
    truncated = replace(_trade(start, profit=999), exit_reason="END_OF_DATA", duration_bars=4)
    clean = wf._scoped_outcome(_outcome([valid, truncated], limit=10, forged=True), frame)
    assert clean.trades == (valid,)
    assert clean.metrics.net_profit == -10
    assert clean.equity_curve.equity.iloc[-1] == 490
    assert clean.equity_curve.timestamp.max() <= frame.timestamp.max()
    assert clean.rejected_candidates[-1]["reason"] == "WF_TRUNCATED_EXIT"


def test_completed_predefined_holding_horizon_is_not_false_truncation():
    frame = wf._window_input(_bars(20), 0, 20, stage="test", warmup=0, purge=0, initial_balance=1_000)
    start = frame.iloc[0].timestamp
    trade = replace(_trade(start), exit_reason="END_OF_DATA", duration_bars=10,
                    exit_time=frame.iloc[9].timestamp.isoformat())
    clean = wf._scoped_outcome(_outcome([trade], limit=10), frame)
    assert clean.trades == (trade,)


def test_selection_uses_validation_only_and_test_windows_are_disjoint():
    test_calls = []

    def callback(frame, params):
        context = frame.attrs["walk_forward_context"]
        stage = context["stage"]
        if stage == "test":
            test_calls.append((context["evaluation_start_utc"], context["evaluation_end_utc"], params["variant"]))
        # The loser on validation would be a huge winner on test. It must never
        # be evaluated there, and future test PnL must not alter the choice.
        profit = (10 if params["variant"] == "validation_winner" else -10) if stage == "validation" else (-50 if params["variant"] == "validation_winner" else 99999)
        return _outcome([_trade(pd.Timestamp(context["evaluation_start_utc"]), profit=profit)])

    result = wf.WalkForwardOptimizer(train_size=20, validation_size=10, test_size=10,
                                      warmup_size=5, selection_metric="net_profit").run(
        _bars(60), [{"variant": "validation_winner"}, {"variant": "test_winner"}], callback)
    assert len(test_calls) == len(result.folds) == 3
    assert all(item[2] == "validation_winner" for item in test_calls)
    assert result.aggregate_test_metrics.net_profit == -150
    assert all(pd.Timestamp(left[1]) < pd.Timestamp(right[0]) for left, right in zip(test_calls, test_calls[1:]))


def test_native_callback_suppresses_warmup_candidates(monkeypatch):
    bars = _bars(30)
    frame = wf._window_input(bars, 10, 30, stage="validation", warmup=10, purge=1, initial_balance=800)
    candidates = tuple(TradeCandidate(
        timestamp=bars.iloc[source].timestamp, symbol="EURUSD", direction="BUY", sl_price=1.0, tp_price=1.2,
        signal_id=label, available_at_utc=bars.iloc[source + 1].timestamp,
    ) for source, label in ((1, "warmup"), (9, "valid")))
    monkeypatch.setattr(wf, "generate_strategy_candidates", lambda *_args, **_kwargs: candidates)
    outcome = wf._run_param_backtest(frame, "EURUSD", {"slippage_points": 0})
    assert [trade.signal_id for trade in outcome.trades] == ["valid"]
    assert outcome.settings.initial_balance == 800


def test_cost_assumptions_cannot_be_optimized():
    optimizer = wf.WalkForwardOptimizer(train_size=10, validation_size=5, test_size=5)
    with pytest.raises(ValueError, match="costs must be fixed"):
        optimizer.run(_bars(), [{"slippage_points": 0}, {"slippage_points": 5}], lambda *_: None)
    grid = wf._default_parameter_grid()
    assert len({(row["spread_points"], row["slippage_points"]) for row in grid}) == 1
    assert len({row["trailing_distance_points"] for row in grid}) == 3


def test_calendar_windows_include_only_historical_warmup_and_report_audit(tmp_path, monkeypatch):
    bars = _bars(45, "D")
    cfg = wf.WalkForwardSettings(train_days=10, validation_days=5, test_days=5,
                                 step_days=5, warmup_bars=3, purge_bars=1)
    path = tmp_path / "EURUSD_M5.csv"
    bars.to_csv(path, index=False)
    monkeypatch.setattr(wf, "_find_history_csv", lambda *_: path)
    monkeypatch.setattr(wf, "load_historical_csv", lambda *_args, **_kwargs: (bars.copy(), None))

    def callback(frame, symbol, params):
        context = frame.attrs["walk_forward_context"]
        assert frame.iloc[-1].timestamp == pd.Timestamp(context["evaluation_end_utc"])
        assert context["warmup_rows"] <= 3
        return _outcome([_trade(pd.Timestamp(context["evaluation_start_utc"]), profit=2)])

    monkeypatch.setattr(wf, "_run_param_backtest", callback)
    summary = wf.run_walk_forward_for_symbols(data_dir=tmp_path, symbols=["EURUSD"],
                                               settings=cfg, parameter_grid=[{}], report_dir=tmp_path / "report")
    report = json.loads((tmp_path / "report" / "summary.json").read_text())
    assert summary["test_used_for_selection"] is False
    assert report["warmup_bars"] == 3
    assert report["purge_bars"] == 1
    assert report["configurations_tested"] == 1
    assert report["operationally_eligible"] is False
    windows = pd.read_csv(tmp_path / "report" / "windows.csv")
    audit = json.loads(windows.iloc[0].temporal_audit)
    assert audit["validation"]["warmup_rows"] == 3
    assert pd.Timestamp(windows.iloc[0].train_end) < pd.Timestamp(windows.iloc[0].validation_start)
