from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.backtesting import (
    Backtester,
    BacktestSettings,
    CostModel,
    MonteCarloSimulator,
    PerformanceReportWriter,
    StressTester,
    TradeCandidate,
    TradeResult,
    calculate_metrics,
    classify_strategy_promotion,
    build_master_validation_report,
    load_historical_csv,
    robust_validation_score,
    run_backtest_for_symbols,
    run_monte_carlo_report,
    run_stress_report,
)
from agi_style_forex_bot_mt5.backtesting.walk_forward_optimizer import WalkForwardOptimizer
from agi_style_forex_bot_mt5.mt5_history_exporter import MT5HistoryExporter


def _candles() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=6, freq="h", tz="UTC"),
            "open": [1.1000, 1.1000, 1.1010, 1.1020, 1.1010, 1.1005],
            "high": [1.1010, 1.1035, 1.1020, 1.1025, 1.1015, 1.1010],
            "low": [1.0996, 1.0995, 1.0980, 1.1000, 1.0990, 1.0995],
            "close": [1.1000, 1.1020, 1.0990, 1.1010, 1.1005, 1.1000],
            "spread_points": [10, 10, 10, 10, 10, 10],
        }
    )


def _historical_csv(path: Path, *, rows: int = 260) -> None:
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    price = 1.1000
    data = []
    for idx, timestamp in enumerate(timestamps):
        price += 0.00005
        open_ = price
        close = price + (0.00003 if idx % 2 == 0 else -0.00002)
        high = max(open_, close) + 0.00010
        low = min(open_, close) - 0.00010
        data.append(
            {
                "time": timestamp.isoformat(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "tick_volume": 1000 + idx,
                "spread": 10,
            }
        )
    pd.DataFrame(data).to_csv(path, index=False)


def test_backtester_applies_costs_and_core_metrics() -> None:
    settings = BacktestSettings(
        initial_balance=10_000,
        cost_model=CostModel(
            spread_points=10,
            slippage_points=0,
            point=0.0001,
            tick_size=0.0001,
            tick_value=10,
            max_spread_points=25,
        ),
    )
    candidates = [
        TradeCandidate(
            timestamp="2026-01-01T00:00:00Z",
            symbol="EURUSD",
            direction="BUY",
            sl_price=1.0990,
            tp_price=1.1020,
            lot=1.0,
            signal_id="win",
        ),
        TradeCandidate(
            timestamp="2026-01-01T02:00:00Z",
            symbol="EURUSD",
            direction="BUY",
            sl_price=1.0990,
            tp_price=1.1030,
            lot=1.0,
            signal_id="loss",
        ),
    ]

    outcome = Backtester(settings).run(_candles(), candidates)

    assert outcome.metrics.trades_total == 2
    assert outcome.metrics.win_rate_pct == 50.0
    assert outcome.metrics.profit_factor > 0
    assert outcome.metrics.max_consecutive_losses == 1
    assert outcome.metrics.average_duration_seconds >= 0
    assert outcome.rejected_candidates == ()


def test_backtester_rejects_high_spread_candidate() -> None:
    settings = BacktestSettings(
        cost_model=CostModel(spread_points=30, max_spread_points=25),
    )
    candidate = TradeCandidate(
        timestamp="2026-01-01T00:00:00Z",
        symbol="EURUSD",
        direction="BUY",
        sl_price=1.0990,
        tp_price=1.1020,
    )

    outcome = Backtester(settings).run(_candles().drop(columns=["spread_points"]), [candidate])

    assert outcome.metrics.trades_total == 0
    assert outcome.rejected_candidates[0]["reason"] == "spread exceeds configured maximum"


def test_monte_carlo_is_reproducible_with_seed() -> None:
    profits = [100, -50, 80, -20, -10]

    first = MonteCarloSimulator(seed=42).run(profits, iterations=100)
    second = MonteCarloSimulator(seed=42).run(profits, iterations=100)

    assert first.final_equity_percentiles == second.final_equity_percentiles
    assert first.max_drawdown_percentiles == second.max_drawdown_percentiles


def test_stress_and_reports(tmp_path: Path) -> None:
    settings = BacktestSettings(
        cost_model=CostModel(
            spread_points=10,
            point=0.0001,
            tick_size=0.0001,
            tick_value=10,
            max_spread_points=25,
        ),
    )
    outcome = Backtester(settings).run(
        _candles(),
        [
            TradeCandidate(
                timestamp="2026-01-01T00:00:00Z",
                symbol="EURUSD",
                direction="BUY",
                sl_price=1.0990,
                tp_price=1.1020,
                signal_id="report",
            )
        ],
    )

    stressed = StressTester().spread_slippage_sensitivity(outcome.trades)
    artifacts = PerformanceReportWriter().write(outcome, tmp_path)

    assert stressed
    assert Path(artifacts.summary_json_path).exists()
    assert Path(artifacts.trades_csv_path).exists()
    assert Path(artifacts.equity_curve_csv_path).exists()


def test_valid_historical_csv_loads_and_reports_quality(tmp_path: Path) -> None:
    path = tmp_path / "EURUSD_M5.csv"
    _historical_csv(path)

    frame, quality = load_historical_csv(path, symbol="EURUSD", timeframe="M5")

    assert len(frame) == 260
    assert quality.symbol == "EURUSD"
    assert quality.duplicate_timestamps == 0
    assert quality.fingerprint


def test_historical_csv_missing_required_columns_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame({"time": ["2026-01-01"], "open": [1.0]}).to_csv(path, index=False)

    with pytest.raises(ValueError, match="missing columns"):
        load_historical_csv(path, symbol="EURUSD")


def test_empty_historical_csv_fails(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("time,open,high,low,close,tick_volume\n", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        load_historical_csv(path, symbol="EURUSD")


def test_break_even_moves_stop_to_non_loss() -> None:
    settings = BacktestSettings(
        cost_model=CostModel(spread_points=0, point=0.0001, tick_size=0.0001, tick_value=10),
        break_even_trigger_r=0.6,
        break_even_lock_points=0,
    )
    candles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
            "open": [1.1000, 1.1000, 1.1000],
            "high": [1.1000, 1.1008, 1.1002],
            "low": [1.1000, 1.0999, 1.0998],
            "close": [1.1000, 1.1002, 1.1000],
        }
    )
    outcome = Backtester(settings).run(
        candles,
        [TradeCandidate(timestamp=candles.iloc[0]["timestamp"], symbol="EURUSD", direction="BUY", sl_price=1.0990, tp_price=1.1030)],
    )

    assert outcome.trades[0].final_sl_price >= outcome.trades[0].entry_price


def test_trailing_stop_for_buy_never_retreats() -> None:
    settings = BacktestSettings(
        cost_model=CostModel(spread_points=0, point=0.0001, tick_size=0.0001, tick_value=10),
        trailing_start_r=0.8,
        trailing_distance_points=4,
    )
    outcome = Backtester(settings).run(
        _candles(),
        [TradeCandidate(timestamp="2026-01-01T00:00:00Z", symbol="EURUSD", direction="BUY", sl_price=1.0990, tp_price=1.1050)],
    )

    trade = outcome.trades[0]
    assert trade.final_sl_price >= trade.initial_sl_price


def test_profit_factor_drawdown_and_expectancy_are_reproducible() -> None:
    trades = [
        {"profit": 100, "r_multiple": 1, "exit_time": "2026-01-01T00:00:00Z", "entry_time": "2026-01-01T00:00:00Z"},
        {"profit": -50, "r_multiple": -0.5, "exit_time": "2026-01-02T00:00:00Z", "entry_time": "2026-01-02T00:00:00Z"},
        {"profit": 50, "r_multiple": 0.5, "exit_time": "2026-01-03T00:00:00Z", "entry_time": "2026-01-03T00:00:00Z"},
    ]
    metrics = calculate_metrics(trades, initial_balance=10_000)

    assert metrics.profit_factor == 3.0
    assert metrics.expectancy == pytest.approx(100 / 3)
    assert metrics.average_r == pytest.approx(1 / 3)
    assert metrics.max_drawdown_pct < 0


def test_batch_reports_are_created(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    report_dir = tmp_path / "reports"
    data_dir.mkdir()
    _historical_csv(data_dir / "EURUSD_M5.csv", rows=260)

    result = run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD",), report_dir=report_dir)

    expected = {
        "summary.json",
        "summary.csv",
        "trades.csv",
        "equity_curve.csv",
        "by_symbol.csv",
        "by_regime.csv",
        "by_session.csv",
        "by_weekday.csv",
        "by_hour_utc.csv",
        "report.html",
    }
    assert expected.issubset({path.name for path in report_dir.iterdir()})
    assert result.summary["mode"] == "backtest"
    assert result.summary["execution_attempted"] is False


def test_strategy_promotion_gate_classifies_statuses() -> None:
    approved_metrics = calculate_metrics(
        [{"profit": 10, "r_multiple": 0.2, "exit_time": f"2026-01-{(idx % 28) + 1:02d}T00:00:00Z", "entry_time": "2026-01-01T00:00:00Z"} for idx in range(300)]
    )
    approved_trades = pd.DataFrame(
        {
            "profit": [10] * 300,
            "exit_time": pd.date_range("2026-01-01", periods=300, freq="D", tz="UTC"),
        }
    )
    approved = classify_strategy_promotion(
        approved_metrics,
        approved_trades,
        oos_positive=True,
        monte_carlo_ruin_ok=True,
        spread_slippage_ok=True,
    )
    rejected = classify_strategy_promotion(calculate_metrics([]), pd.DataFrame())
    watchlist = classify_strategy_promotion(approved_metrics, approved_trades)

    assert approved.status == "APPROVED_FOR_SHADOW_OBSERVATION"
    assert watchlist.status == "WATCHLIST"
    assert rejected.status == "REJECTED"


def test_backtest_cli_accepts_mode(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_run_backtest_for_symbols(**kwargs):
        return SimpleNamespace(
            summary={
                "mode": "backtest",
                "symbols_tested": 1,
                "total_trades": 0,
                "net_return_pct": 0,
                "max_drawdown_pct": 0,
                "profit_factor": 0,
                "winrate": 0,
                "expectancy_r": 0,
                "sharpe": None,
                "sortino": None,
                "reports_created": [],
                "execution_attempted": False,
            }
        )

    monkeypatch.setattr(cli, "run_backtest_for_symbols", fake_run_backtest_for_symbols)
    code = cli.main(["--mode", "backtest", "--symbol", "EURUSD", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)])
    assert code == 0
    assert '"mode": "backtest"' in capsys.readouterr().out


def test_export_history_cli_accepts_mode_and_no_order_send(monkeypatch, tmp_path: Path, capsys) -> None:
    class FakeExporter:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run(self):
            return SimpleNamespace(
                mode="export-history",
                mt5_connected=False,
                symbols_requested=1,
                files_created=0,
                rows_exported=0,
                execution_attempted=False,
            )

    monkeypatch.setattr(cli, "MT5HistoryExporter", FakeExporter)
    code = cli.main(["--mode", "export-history", "--symbol", "EURUSD", "--output-dir", str(tmp_path)])
    assert code == 0
    assert '"mode": "export-history"' in capsys.readouterr().out


def test_export_history_never_calls_order_send(tmp_path: Path) -> None:
    class FakeMT5:
        TIMEFRAME_M5 = 5

        def __init__(self) -> None:
            self.calls: list[str] = []

        def initialize(self) -> bool:
            self.calls.append("initialize")
            return True

        def symbol_info(self, symbol: str):
            self.calls.append("symbol_info")
            return SimpleNamespace(name=symbol)

        def copy_rates_from_pos(self, symbol: str, timeframe, start_pos: int, count: int):
            self.calls.append("copy_rates_from_pos")
            return [{"time": 1770000000, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "tick_volume": 100, "spread": 10}]

        def last_error(self):
            return (0, "")

        def order_send(self, request):
            self.calls.append("order_send")
            raise AssertionError("order_send must not be called")

    fake = FakeMT5()
    summary = MT5HistoryExporter(symbols=("EURUSD",), timeframes=("M5",), output_dir=tmp_path, mt5_client=fake).run()

    assert summary.files_created == 1
    assert "order_send" not in fake.calls


def _trade(profit: float, *, signal_id: str = "t") -> TradeResult:
    return TradeResult(
        signal_id=signal_id,
        symbol="EURUSD",
        direction="BUY",
        entry_time="2026-01-01T00:00:00Z",
        exit_time="2026-01-01T01:00:00Z",
        entry_price=1.1000,
        exit_price=1.1010,
        initial_sl_price=1.0990,
        final_sl_price=1.0990,
        tp_price=1.1020,
        lot=1.0,
        profit=profit,
        r_multiple=profit / 100.0,
        exit_reason="TP" if profit > 0 else "SL",
        duration_bars=1,
        duration_seconds=3600,
        mae=-0.0002,
        mfe=0.0004,
        spread_points=10,
        slippage_points=1,
        commission=0,
        point=0.0001,
        tick_value=10,
        tick_size=0.0001,
        metadata={"session": "LONDON", "regime": "TREND_UP"},
    )


def test_walk_forward_respects_temporal_order_and_no_leakage() -> None:
    candles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=90, freq="D", tz="UTC"),
            "open": [1.1] * 90,
            "high": [1.2] * 90,
            "low": [1.0] * 90,
            "close": [1.15] * 90,
        }
    )

    def callback(frame: pd.DataFrame, params):
        candidate = TradeCandidate(
            timestamp=frame.iloc[0]["timestamp"],
            symbol="EURUSD",
            direction="BUY",
            sl_price=1.0,
            tp_price=1.2,
        )
        return Backtester().run(frame, [candidate])

    result = WalkForwardOptimizer(train_size=30, validation_size=10, test_size=10, step_size=10).run(
        candles,
        [{"x": 1}, {"x": 2}],
        callback,
    )
    fold = result.folds[0]
    assert pd.Timestamp(fold.train_end) < pd.Timestamp(fold.validation_start)
    assert pd.Timestamp(fold.validation_end) < pd.Timestamp(fold.test_start)


def test_robust_scoring_penalizes_few_trades_and_oos_deterioration() -> None:
    weak = calculate_metrics([_trade(10)])
    strong_train = calculate_metrics([_trade(100) for _ in range(50)])
    poor_test = calculate_metrics([_trade(-50) for _ in range(20)])

    few = robust_validation_score(train_metrics=weak, validation_metrics=weak, test_metrics=weak)
    deteriorated = robust_validation_score(
        train_metrics=strong_train,
        validation_metrics=strong_train,
        test_metrics=poor_test,
    )

    assert few.classification != "APPROVED_FOR_SHADOW_OBSERVATION"
    assert deteriorated.classification == "REJECTED"


def test_monte_carlo_report_is_reproducible_and_has_ruin_probability(tmp_path: Path) -> None:
    trades = [_trade(100), _trade(-50), _trade(80), _trade(-30)]

    first = run_monte_carlo_report(trades=trades, report_dir=tmp_path / "a", seed=42, iterations=100)
    second = run_monte_carlo_report(trades=trades, report_dir=tmp_path / "b", seed=42, iterations=100)

    assert first["probability_of_ruin"] == second["probability_of_ruin"]
    assert "fifth_percentile_return_pct" in first
    assert Path(first["reports_created"][0]).exists()


def test_stress_tester_worsens_with_higher_spread_and_removes_top_trades(tmp_path: Path) -> None:
    trades = [_trade(200, signal_id="best"), _trade(50), _trade(-20), _trade(40)]
    rows = StressTester().comprehensive(trades)
    spread_x1 = next(row for row in rows if row.scenario == "spread_multiplier" and row.parameters["spread_multiplier"] == 1.0)
    spread_x3 = next(row for row in rows if row.scenario == "spread_multiplier" and row.parameters["spread_multiplier"] == 3.0)
    top5 = next(row for row in rows if row.scenario == "remove_best_percent" and row.parameters["removed_pct"] == 5)
    report = run_stress_report(trades=trades, report_dir=tmp_path)

    assert spread_x3.metrics.net_profit < spread_x1.metrics.net_profit
    assert top5.metrics.net_profit < spread_x1.metrics.net_profit
    assert report["execution_attempted"] is False


def test_validation_report_consolidates_results(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    (root / "backtests").mkdir(parents=True)
    (root / "walk_forward").mkdir()
    (root / "monte_carlo").mkdir()
    (root / "stress").mkdir()
    (root / "data_quality").mkdir()
    (root / "broker_costs").mkdir()
    (root / "benchmarks").mkdir()
    (root / "competitive_scorecard").mkdir()
    (root / "research").mkdir()
    (root / "backtests" / "summary.json").write_text('{"total_trades":300,"profit_factor":1.5,"expectancy_r":0.1,"max_drawdown_pct":-5}', encoding="utf-8")
    for folder in ("walk_forward", "monte_carlo", "stress"):
        (root / folder / "summary.json").write_text('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION"}', encoding="utf-8")
    (root / "data_quality" / "summary.json").write_text('{"classification":"OK"}', encoding="utf-8")
    (root / "broker_costs" / "broker_cost_profile.json").write_text('{"classification":"OK"}', encoding="utf-8")
    (root / "benchmarks" / "summary.json").write_text('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION"}', encoding="utf-8")
    (root / "competitive_scorecard" / "competitive_scorecard.json").write_text('{"classification":"COMPETITIVE_CANDIDATE"}', encoding="utf-8")
    (root / "research" / "research_summary.json").write_text('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION"}', encoding="utf-8")
    (root / "research" / "recommended_strategy_mix.json").write_text('[{"symbol":"EURUSD"}]', encoding="utf-8")
    (root / "research" / "candidate_registry.json").write_text('[{"candidate_id":"cand_1"}]', encoding="utf-8")

    report = build_master_validation_report(reports_root=root, output_dir=root / "validation")

    assert report["classification"] == "APPROVED_FOR_SHADOW_OBSERVATION"
    assert len(report["reports_created"]) == 3


def test_phase5_cli_modes_accept_and_return_no_execution(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "run_walk_forward_for_symbols", lambda **kwargs: {"mode": "walk-forward", "input_files": [], "reports_created": [], "classification": "WATCHLIST", "execution_attempted": False})
    monkeypatch.setattr(cli, "run_monte_carlo_report", lambda **kwargs: {"mode": "monte-carlo", "input_files": [], "reports_created": [], "classification": "WATCHLIST", "execution_attempted": False})
    monkeypatch.setattr(cli, "run_stress_report", lambda **kwargs: {"mode": "stress-test", "input_files": [], "reports_created": [], "classification": "WATCHLIST", "execution_attempted": False})
    monkeypatch.setattr(cli, "build_master_validation_report", lambda **kwargs: {"mode": "validation-report", "input_files": [], "reports_created": [], "classification": "WATCHLIST", "execution_attempted": False})

    commands = [
        ["--mode", "walk-forward", "--symbol", "EURUSD", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)],
        ["--mode", "monte-carlo", "--trades", str(tmp_path / "trades.csv"), "--report-dir", str(tmp_path)],
        ["--mode", "stress-test", "--symbol", "EURUSD", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)],
        ["--mode", "validation-report", "--reports-root", str(tmp_path), "--output-dir", str(tmp_path)],
    ]
    for command in commands:
        assert cli.main(command) == 0
        assert '"execution_attempted": false' in capsys.readouterr().out
