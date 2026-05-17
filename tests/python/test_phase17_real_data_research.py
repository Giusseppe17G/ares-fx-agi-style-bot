from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.real_data_research import RealDataResearchConfig, RealDataResearchRunner


STAGE_NAMES = (
    "MT5_DIAGNOSE",
    "EXPORT_HISTORY",
    "DATA_QUALITY",
    "BROKER_COST_PROFILE",
    "STRUCTURE_REPORT",
    "STRATEGY_DIAGNOSE",
    "BACKTEST",
    "WALK_FORWARD",
    "MONTE_CARLO",
    "STRESS_TEST",
    "RESEARCH",
    "BENCHMARK",
    "COMPETITIVE_SCORECARD",
    "FULL_VALIDATION",
)


def _override(name: str):
    def run() -> dict[str, object]:
        payload: dict[str, object] = {"mode": name.lower(), "classification": "OK", "execution_attempted": False}
        if name in {"MT5_DIAGNOSE", "EXPORT_HISTORY"}:
            payload["mt5_connected"] = True
        if name == "FULL_VALIDATION":
            payload["final_decision"] = "CONTINUE_FORWARD_SHADOW"
        return payload

    return run


def test_run_real_data_research_script_exists() -> None:
    assert Path("scripts/run_real_data_research.ps1").exists()


def test_cli_accepts_real_data_research(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_run(config: RealDataResearchConfig, **_kwargs):
        return {
            "mode": "real-data-research",
            "run_id": config.run_id,
            "stages": [],
            "final_decision": "NEEDS_MORE_DATA",
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }

    monkeypatch.setattr(cli, "run_real_data_research", fake_run)
    assert cli.main(["--mode", "real-data-research", "--symbols", "EURUSD", "--bars", "100", "--output-root", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "real-data-research"
    assert output["execution_attempted"] is False
    assert output["order_send_called"] is False
    assert output["order_check_called"] is False


def test_real_data_research_creates_run_folder_and_summary(tmp_path: Path) -> None:
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), bars=10, run_id="test-real-data-research")
    overrides = {name: _override(name) for name in STAGE_NAMES}

    summary = RealDataResearchRunner(config, stage_overrides=overrides).run()

    run_dir = tmp_path / "test-real-data-research"
    assert (run_dir / "logs").is_dir()
    assert (run_dir / "historical").is_dir()
    assert (run_dir / "reports").is_dir()
    assert (run_dir / "sqlite").is_dir()
    assert (run_dir / "final_summary.json").exists()
    assert (run_dir / "final_summary.html").exists()
    assert (run_dir / "final_summary_compact.json").exists()
    assert (run_dir / "final_summary_compact.txt").exists()
    assert summary["execution_attempted"] is False


def test_real_data_research_missing_history_needs_more_data(tmp_path: Path) -> None:
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), bars=10, run_id="missing-history")
    overrides = {name: _override(name) for name in STAGE_NAMES}

    summary = RealDataResearchRunner(config, stage_overrides=overrides).run()

    assert summary["final_decision"] == "NEEDS_MORE_DATA"
    assert summary["top_5_issues_blocking_progress"]
    assert summary["execution_attempted"] is False


def test_real_data_research_stage_failure_is_reflected(tmp_path: Path) -> None:
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), bars=10, run_id="stage-failure")
    overrides = {name: _override(name) for name in STAGE_NAMES}

    def fail_stage() -> dict[str, object]:
        raise RuntimeError("mock stage failure")

    overrides["DATA_QUALITY"] = fail_stage
    summary = RealDataResearchRunner(config, stage_overrides=overrides).run()

    failed = [stage for stage in summary["stages"] if stage["status"] == "FAILED"]
    assert failed
    assert "mock stage failure" in failed[0]["error_message"]
    assert summary["execution_attempted"] is False


def test_real_data_research_summary_flags_no_execution_calls(tmp_path: Path) -> None:
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), bars=10, run_id="no-execution")
    overrides = {name: _override(name) for name in STAGE_NAMES}

    summary = RealDataResearchRunner(config, stage_overrides=overrides).run()

    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False
    for stage in summary["stages"]:
        assert stage["execution_attempted"] is False


def test_symbols_string_converts_to_tuple() -> None:
    config = RealDataResearchConfig(symbols="EURUSD,gbpusd", run_id="symbols")

    assert config.symbols == ("EURUSD", "GBPUSD")


def test_backtest_zero_trades_creates_empty_contract_files(tmp_path: Path) -> None:
    runner = RealDataResearchRunner(RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), run_id="zero-trades"))
    runner._prepare_dirs()
    _write_history(runner.historical_dir / "EURUSD_M5.csv", rows=40)

    summary = runner._backtest()

    assert summary["classification"] == "WARNING_NO_TRADES"
    trades = pd.read_csv(runner.reports_dir / "backtests" / "trades.csv")
    assert list(trades.columns)[:10] == [
        "signal_id",
        "symbol",
        "direction",
        "entry_time",
        "exit_time",
        "entry_price",
        "exit_price",
        "profit",
        "r_multiple",
        "exit_reason",
    ]
    assert (runner.reports_dir / "backtests" / "summary.json").exists()
    assert (runner.reports_dir / "backtests" / "equity_curve.csv").exists()


def test_walk_forward_skips_when_backtest_has_zero_trades(tmp_path: Path) -> None:
    runner = RealDataResearchRunner(RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), run_id="wf-zero"))
    runner._prepare_dirs()
    runner._write_empty_backtest_artifacts(classification="WARNING_NO_TRADES", reason="test")

    summary = runner._walk_forward()

    assert summary["classification"] == "SKIPPED_NO_TRADES"
    assert summary["execution_attempted"] is False


def test_monte_carlo_skips_missing_or_empty_trades(tmp_path: Path) -> None:
    runner = RealDataResearchRunner(RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), run_id="mc-missing"))
    runner._prepare_dirs()

    missing = runner._monte_carlo()
    assert missing["classification"] == "SKIPPED_NO_TRADES"

    runner._write_empty_backtest_artifacts(classification="WARNING_NO_TRADES", reason="test")
    empty = runner._monte_carlo()
    assert empty["classification"] == "SKIPPED_NO_TRADES"
    assert (runner.reports_dir / "monte_carlo" / "summary.json").exists()


def test_stress_and_research_do_not_crash_with_zero_trades(tmp_path: Path) -> None:
    runner = RealDataResearchRunner(RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), run_id="stress-research"))
    runner._prepare_dirs()
    runner._write_empty_backtest_artifacts(classification="WARNING_NO_TRADES", reason="test")

    stress = runner._stress_test()
    research = runner._research()

    assert stress["classification"] == "SKIPPED_NO_TRADES"
    assert research["classification"] == "NEEDS_MORE_DATA"
    assert stress["execution_attempted"] is False
    assert research["execution_attempted"] is False


def test_latest_run_summary_reads_newest_run(tmp_path: Path, capsys) -> None:
    older = tmp_path / "20240101-000000-real-data-research"
    newer = tmp_path / "20240102-000000-real-data-research"
    older.mkdir()
    newer.mkdir()
    (older / "final_summary_compact.json").write_text('{"run_id":"old","final_decision":"NEEDS_MORE_DATA","execution_attempted":false}', encoding="utf-8")
    (newer / "final_summary_compact.json").write_text('{"run_id":"new","final_decision":"CONTINUE_FORWARD_SHADOW","execution_attempted":false}', encoding="utf-8")

    assert cli.main(["--mode", "latest-run-summary", "--runs-root", str(tmp_path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "new"
    assert output["execution_attempted"] is False


def test_stage_statuses_are_normalized(tmp_path: Path) -> None:
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), bars=10, run_id="status-normalized")
    overrides = {name: _override(name) for name in STAGE_NAMES}
    overrides["MONTE_CARLO"] = lambda: {"classification": "SKIPPED_NO_TRADES", "execution_attempted": False}

    summary = RealDataResearchRunner(config, stage_overrides=overrides).run()

    statuses = {stage["status"] for stage in summary["stages"]}
    assert statuses <= {"PASSED", "WARNING", "FAILED", "SKIPPED"}
    assert any(stage["stage_name"] == "MONTE_CARLO" and stage["status"] == "SKIPPED" for stage in summary["stages"])


def _write_history(path: Path, *, rows: int) -> None:
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    data = []
    for index in range(rows):
        price = 1.1000 + index * 0.00001
        data.append(
            {
                "time": (start + pd.Timedelta(minutes=5 * index)).isoformat(),
                "open": price,
                "high": price + 0.0001,
                "low": price - 0.0001,
                "close": price,
                "tick_volume": 100,
                "spread": 10,
            }
        )
    pd.DataFrame(data).to_csv(path, index=False)
