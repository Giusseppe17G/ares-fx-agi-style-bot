from __future__ import annotations

import json
from pathlib import Path

import pytest

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter
from agi_style_forex_bot_mt5.validation_pipeline import MasterDecisionEngine, PipelineConfig, PipelineLock, PipelineRunner


def test_pipeline_config_serializes(tmp_path: Path) -> None:
    config = PipelineConfig.from_paths(
        symbols=("eurusd", "gbpusd"),
        timeframes=("m5", "h1"),
        data_dir=tmp_path / "historical",
        reports_root=tmp_path / "reports",
        sqlite_path=tmp_path / "db.sqlite3",
        log_dir=tmp_path / "logs",
        output_dir=tmp_path / "full",
        bars=100,
        run_export_history=False,
        fail_fast=True,
        seed=42,
    )

    payload = config.to_dict()

    assert payload["symbols"] == ("EURUSD", "GBPUSD")
    assert payload["timeframes"] == ("M5", "H1")
    assert payload["execution_attempted"] is False if "execution_attempted" in payload else True


def test_pipeline_runner_executes_mocked_stages_in_order(tmp_path: Path) -> None:
    order: list[str] = []
    reports = tmp_path / "reports"
    output = tmp_path / "full"

    def stage(name: str, path: Path, payload: dict[str, object] | None = None):
        def run():
            order.append(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload or {"classification": "OK", "execution_attempted": False}), encoding="utf-8")
            return {"mode": name.lower(), "classification": "OK", "execution_attempted": False}

        return run

    config = PipelineConfig(
        symbols=("EURUSD",),
        reports_root=str(reports),
        output_dir=str(output),
        sqlite_path=str(tmp_path / "db.sqlite3"),
        run_export_history=False,
        run_walk_forward=False,
        run_monte_carlo=False,
        run_stress_test=False,
        run_research=False,
        run_benchmark=False,
        run_competitive_scorecard=False,
        run_broker_quality=False,
        run_simulation_calibration=False,
        run_paper_vs_backtest=False,
        run_validation_report=False,
    )
    overrides = {
        "DATA_QUALITY": stage("DATA_QUALITY", reports / "data_quality" / "summary.json", {"classification": "OK"}),
        "BROKER_COST_PROFILE": stage("BROKER_COST_PROFILE", reports / "broker_costs" / "broker_cost_profile.json", {"classification": "OK"}),
        "BACKTEST": stage("BACKTEST", reports / "backtests" / "summary.json", {"total_trades": 10}),
    }

    summary = PipelineRunner(config, stage_overrides=overrides).run()

    assert order == ["DATA_QUALITY", "BROKER_COST_PROFILE", "BACKTEST"]
    assert summary["mode"] == "full-validation"
    assert summary["execution_attempted"] is False
    assert (output / "pipeline_summary.json").exists()


def test_pipeline_lock_blocks_double_execution(tmp_path: Path) -> None:
    lock = PipelineLock(tmp_path / "pipeline.lock")
    lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            PipelineLock(tmp_path / "pipeline.lock").acquire()
    finally:
        lock.release()


def test_stage_missing_output_marks_failed(tmp_path: Path) -> None:
    config = PipelineConfig(
        symbols=("EURUSD",),
        reports_root=str(tmp_path / "reports"),
        output_dir=str(tmp_path / "full"),
        sqlite_path=str(tmp_path / "db.sqlite3"),
        run_export_history=False,
        run_cost_profile=False,
        run_backtest=False,
        run_walk_forward=False,
        run_monte_carlo=False,
        run_stress_test=False,
        run_research=False,
        run_benchmark=False,
        run_competitive_scorecard=False,
        run_broker_quality=False,
        run_simulation_calibration=False,
        run_paper_vs_backtest=False,
        run_validation_report=False,
    )
    summary = PipelineRunner(config, stage_overrides={"DATA_QUALITY": lambda: {"classification": "OK", "execution_attempted": False}}).run()

    assert summary["stages_failed"] == 1
    assert "missing expected outputs" in summary["stage_results"][1]["error_message"]


def test_master_decision_rules(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    output = tmp_path / "full"
    engine = MasterDecisionEngine()

    assert engine.decide(reports_root=root, output_dir=output, symbols=("EURUSD",)).final_decision == "NEEDS_MORE_DATA"
    _write(root / "data_quality" / "summary.json", {"classification": "OK"})
    _write(root / "broker_costs" / "broker_cost_profile.json", {"classification": "OK"})
    _write(root / "backtests" / "summary.json", {"total_trades": 10})
    assert engine.decide(reports_root=root, output_dir=output, symbols=("EURUSD",)).final_decision == "NEEDS_STRATEGY_RESEARCH"
    _write(root / "backtests" / "summary.json", {"total_trades": 300})
    _write(root / "monte_carlo" / "summary.json", {"probability_of_ruin": 0.25})
    assert engine.decide(reports_root=root, output_dir=output, symbols=("EURUSD",)).final_decision == "REJECTED"
    _write(root / "monte_carlo" / "summary.json", {"probability_of_ruin": 0.01})
    _write(root / "broker_quality" / "summary.json", {"classification": "NOT_READY"})
    assert engine.decide(reports_root=root, output_dir=output, symbols=("EURUSD",)).final_decision == "NEEDS_BROKER_FIX"
    _write(root / "broker_quality" / "summary.json", {"classification": "EXECUTION_READY_SHADOW_ONLY"})
    _write(root / "paper_vs_backtest" / "summary.json", {"classification": "BACKTEST_TOO_OPTIMISTIC"})
    assert engine.decide(reports_root=root, output_dir=output, symbols=("EURUSD",)).final_decision == "NEEDS_COST_RECALIBRATION"


def test_cli_full_validation_and_telegram(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "run_full_validation",
        lambda config: {
            "mode": "full-validation",
            "pipeline_run_id": "fvp_test",
            "stages_passed": 1,
            "stages_warning": 0,
            "stages_failed": 0,
            "final_decision": "CONTINUE_FORWARD_SHADOW",
            "reports_created": [],
            "execution_attempted": False,
        },
    )
    sqlite_path = tmp_path / "db.sqlite3"
    assert cli.main(["--mode", "full-validation", "--sqlite", str(sqlite_path), "--output-dir", str(tmp_path / "full"), "--skip-export-history"]) == 0
    assert '"execution_attempted": false' in capsys.readouterr().out

    monkeypatch.chdir(tmp_path)
    summary_dir = tmp_path / "data" / "reports" / "full_validation"
    summary_dir.mkdir(parents=True)
    (summary_dir / "pipeline_summary.json").write_text('{"pipeline_run_id":"fvp_test","final_decision":"CONTINUE_FORWARD_SHADOW","execution_attempted":false}', encoding="utf-8")
    db = TelemetryDatabase(tmp_path / "tg.sqlite3")
    try:
        result = TelegramCommandCenter(database=db, allowed_chat_id="123").process_update({"message": {"chat": {"id": "123"}, "text": "/validation"}})
        assert result.accepted is True
        assert "fvp_test" in result.response_text
    finally:
        db.close()


def test_run_full_validation_script_exists() -> None:
    assert Path("scripts/run_full_validation.ps1").exists()


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

