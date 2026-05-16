from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.benchmarks import build_competitive_scorecard, generate_baseline_candidates, run_benchmarks
from agi_style_forex_bot_mt5.data_pipeline import (
    build_broker_cost_profile,
    build_dataset_manifest,
    dataset_fingerprint,
    evaluate_history_quality,
)


def _write_history(path: Path, *, duplicate: bool = False, gap: bool = False) -> None:
    times = pd.date_range("2026-01-01", periods=80, freq="5min", tz="UTC")
    if gap:
        times = times.delete([20, 21, 22])
    rows = []
    for index, timestamp in enumerate(times):
        rows.append(
            {
                "time": timestamp.isoformat(),
                "open": 1.1000 + index * 0.0001,
                "high": 1.1010 + index * 0.0001,
                "low": 1.0990 + index * 0.0001,
                "close": 1.1005 + index * 0.0001,
                "tick_volume": 1000 + index,
                "spread": 5 + (index % 10),
            }
        )
    if duplicate:
        rows.append(rows[0].copy())
    pd.DataFrame(rows).to_csv(path, index=False)


def test_data_quality_detects_gaps_duplicates_and_reproducible_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "EURUSD_M5.csv"
    _write_history(path, duplicate=True, gap=True)

    result, gaps, _anomalies = evaluate_history_quality(path, symbol="EURUSD", timeframe="M5")
    first = dataset_fingerprint([result.fingerprint])
    second = dataset_fingerprint([result.fingerprint])

    assert result.duplicate_timestamps == 1
    assert len(gaps) >= 1
    assert first == second


def test_data_quality_reports_are_created(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    report_dir = tmp_path / "reports"
    data_dir.mkdir()
    _write_history(data_dir / "EURUSD_M5.csv")

    summary = build_dataset_manifest(data_dir=data_dir, report_dir=report_dir, symbols=("EURUSD",), timeframes=("M5",))

    assert summary["mode"] == "data-quality"
    assert (report_dir / "dataset_manifest.json").exists()
    assert summary["execution_attempted"] is False


def test_broker_cost_profile_calculates_p95_p99(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    report_dir = tmp_path / "broker_costs"
    data_dir.mkdir()
    _write_history(data_dir / "EURUSD_M5.csv")

    profile = build_broker_cost_profile(data_dir=data_dir, report_dir=report_dir, symbols=("EURUSD",))

    assert profile["symbols"]["EURUSD"]["spread_p95"] >= profile["symbols"]["EURUSD"]["spread_median"]
    assert profile["symbols"]["EURUSD"]["spread_p99"] >= profile["symbols"]["EURUSD"]["spread_p95"]


def test_benchmark_random_is_reproducible_and_runner_generates_baselines(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    report_dir = tmp_path / "benchmarks"
    data_dir.mkdir()
    _write_history(data_dir / "EURUSD_M5.csv")
    candles = pd.read_csv(data_dir / "EURUSD_M5.csv").rename(columns={"time": "timestamp"})

    first = generate_baseline_candidates("RANDOM_ENTRY_WITH_SAME_FREQUENCY", candles, symbol="EURUSD", seed=7)
    second = generate_baseline_candidates("RANDOM_ENTRY_WITH_SAME_FREQUENCY", candles, symbol="EURUSD", seed=7)
    summary = run_benchmarks(data_dir=data_dir, symbols=("EURUSD",), report_dir=report_dir, seed=7)

    assert [item.direction for item in first] == [item.direction for item in second]
    assert (report_dir / "benchmark_results.csv").exists()
    assert summary["execution_attempted"] is False


def test_competitive_scorecard_rejects_without_baseline_or_oos(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    for folder in ("backtests", "benchmarks", "monte_carlo", "stress", "walk_forward"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "backtests" / "summary.json").write_text('{"expectancy_r":0.2,"profit_factor":1.4}', encoding="utf-8")
    (root / "benchmarks" / "summary.json").write_text('{"baselines_beaten_global":1}', encoding="utf-8")
    (root / "monte_carlo" / "summary.json").write_text('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION"}', encoding="utf-8")
    (root / "stress" / "summary.json").write_text('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION"}', encoding="utf-8")
    (root / "stress" / "scenarios.csv").write_text('scenario,parameters,net_profit\nremove_best_percent,"{""removed_pct"": 5}",100\n', encoding="utf-8")
    (root / "walk_forward" / "summary.json").write_text('{"classification":"REJECTED"}', encoding="utf-8")

    summary = build_competitive_scorecard(reports_root=root, output_dir=root / "competitive_scorecard")

    assert summary["classification"] != "COMPETITIVE_CANDIDATE"


def test_validation_report_includes_benchmark_and_data_quality(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    for folder in ("data_quality", "broker_costs", "backtests", "walk_forward", "monte_carlo", "stress", "benchmarks", "competitive_scorecard"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "data_quality" / "summary.json").write_text('{"classification":"OK"}', encoding="utf-8")
    (root / "broker_costs" / "broker_cost_profile.json").write_text('{"classification":"OK"}', encoding="utf-8")
    (root / "backtests" / "summary.json").write_text('{"total_trades":300,"profit_factor":1.5,"expectancy_r":0.1,"max_drawdown_pct":-5}', encoding="utf-8")
    for folder in ("walk_forward", "monte_carlo", "stress", "benchmarks"):
        (root / folder / "summary.json").write_text('{"classification":"APPROVED_FOR_SHADOW_OBSERVATION"}', encoding="utf-8")
    (root / "competitive_scorecard" / "competitive_scorecard.json").write_text('{"classification":"COMPETITIVE_CANDIDATE"}', encoding="utf-8")

    report = cli.build_master_validation_report(reports_root=root, output_dir=root / "validation")

    assert "benchmark" in report["summaries"]
    assert "data_quality" in report["summaries"]


def test_phase6_cli_modes_accept_and_return_no_execution(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "build_dataset_manifest", lambda **kwargs: {"mode": "data-quality", "reports_created": [], "classification": "OK", "execution_attempted": False})
    monkeypatch.setattr(cli, "build_broker_cost_profile", lambda **kwargs: {"mode": "build-cost-profile", "reports_created": [], "classification": "OK", "execution_attempted": False})
    monkeypatch.setattr(cli, "run_benchmarks", lambda **kwargs: {"mode": "benchmark", "reports_created": [], "classification": "WATCHLIST", "execution_attempted": False})
    monkeypatch.setattr(cli, "build_competitive_scorecard", lambda **kwargs: {"mode": "competitive-scorecard", "reports_created": [], "classification": "WEAK_EDGE", "execution_attempted": False})

    commands = [
        ["--mode", "data-quality", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)],
        ["--mode", "build-cost-profile", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)],
        ["--mode", "benchmark", "--symbol", "EURUSD", "--data-dir", str(tmp_path), "--report-dir", str(tmp_path)],
        ["--mode", "competitive-scorecard", "--reports-root", str(tmp_path), "--output-dir", str(tmp_path)],
    ]
    for command in commands:
        assert cli.main(command) == 0
        assert '"execution_attempted": false' in capsys.readouterr().out
