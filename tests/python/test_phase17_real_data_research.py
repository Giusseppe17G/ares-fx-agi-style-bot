from __future__ import annotations

import json
from pathlib import Path

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
