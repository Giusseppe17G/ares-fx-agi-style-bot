from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.calibration import (
    analyze_blocking_reasons,
    load_strategy_diagnostics,
    generate_threshold_grid,
    get_signal_profile,
    is_near_miss,
    parse_profiles,
    run_signal_calibration,
    run_threshold_sweep_report,
)
from agi_style_forex_bot_mt5.real_data_research import RealDataResearchConfig, RealDataResearchRunner, load_latest_run_summary


def test_signal_profile_loads_and_invalid_fails() -> None:
    assert get_signal_profile("BALANCED").name == "BALANCED"
    assert parse_profiles("CONSERVATIVE,ACTIVE")[1].not_for_demo_live is True
    with pytest.raises(ValueError):
        get_signal_profile("LOOSE")


def test_threshold_sweep_generates_combinations() -> None:
    grid = generate_threshold_grid((get_signal_profile("CONSERVATIVE"),))

    assert grid
    assert {item.min_setup_score for item in grid} >= {50.0, 75.0}


def test_near_miss_detects_threshold_window() -> None:
    assert is_near_miss(setup_score=58, threshold=62, blocking_reasons=("score below threshold",), window=5)
    assert not is_near_miss(setup_score=30, threshold=62, blocking_reasons=("score below threshold",), window=5)


def test_blocking_reason_analyzer_counts_motives(tmp_path: Path) -> None:
    result = analyze_blocking_reasons(
        [
            {"symbol": "EURUSD", "metadata": {"blocking_reasons": ("cost fit below threshold",), "component_scores": {"cost_fit": 20}}},
            {"symbol": "GBPUSD", "metadata": {"blocking_reasons": ("cost fit below threshold",), "component_scores": {"cost_fit": 25}}},
        ],
        output_dir=tmp_path,
    )

    assert result["top_blocking_reasons"][0]["blocking_reason"] == "cost fit below threshold"
    assert (tmp_path / "blocking_reasons.csv").exists()


def test_signal_calibration_generates_reports(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    report_dir = tmp_path / "calibration"
    data_dir.mkdir()
    _write_history(data_dir / "EURUSD_M5.csv", rows=320)

    summary = run_signal_calibration(symbols=("EURUSD",), data_dir=data_dir, report_dir=report_dir, profile_name="BALANCED")

    assert summary["mode"] == "signal-calibration"
    assert "reports_created" in summary
    assert (report_dir / "summary.json").exists()
    assert (report_dir / "config_suggestions" / "active.ini").read_text(encoding="utf-8").startswith("; NOT FOR DEMO/LIVE EXECUTION")
    assert summary["execution_attempted"] is False


def test_threshold_sweep_cli_and_no_execution(tmp_path: Path, capsys) -> None:
    data_dir = tmp_path / "historical"
    report_dir = tmp_path / "calibration"
    data_dir.mkdir()
    _write_history(data_dir / "EURUSD_M5.csv", rows=280)

    assert cli.main(["--mode", "threshold-sweep", "--symbol", "EURUSD", "--data-dir", str(data_dir), "--report-dir", str(report_dir), "--profiles", "CONSERVATIVE,BALANCED"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["mode"] == "threshold-sweep"
    assert output["execution_attempted"] is False
    assert (report_dir / "threshold_sweep.csv").exists()


def test_blocking_reasons_cli(tmp_path: Path, capsys) -> None:
    reports_root = tmp_path / "reports"
    diag_dir = reports_root / "strategy_diagnostics" / "EURUSD"
    diag_dir.mkdir(parents=True)
    (diag_dir / "strategy_diagnose.json").write_text(
        json.dumps({"symbol": "EURUSD", "metadata": {"blocking_reasons": ["score below threshold"]}}),
        encoding="utf-8",
    )

    assert cli.main(["--mode", "blocking-reasons", "--reports-root", str(reports_root), "--output-dir", str(tmp_path / "out")]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["top_blocking_reasons"]
    assert output["execution_attempted"] is False


def test_blocked_candidates_produce_blocking_reasons(tmp_path: Path) -> None:
    report_dir = tmp_path / "calibration"

    summary = run_threshold_sweep_report(
        symbols=("EURUSD",),
        data_dir=tmp_path / "empty_historical",
        report_dir=report_dir,
        profiles_value="CONSERVATIVE,BALANCED",
    )

    assert summary["blocked_candidates"] > 0
    assert summary["top_blocking_reasons"]
    assert summary["top_blocking_reasons"][0]["blocking_reason"] == "MISSING_M5_FILE"
    assert (report_dir / "blocking_reasons.csv").exists()


def test_diagnostics_reader_extracts_strategy_diagnose_json(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    diag_dir = reports_root / "strategy_diagnostics" / "EURUSD"
    diag_dir.mkdir(parents=True)
    (diag_dir / "strategy_diagnose.json").write_text(
        json.dumps(
            {
                "diagnostics": [
                    {
                        "symbol": "EURUSD",
                        "strategy_name": "Trend Pullback",
                        "blocking_reasons": ["STRUCTURE_BLOCK"],
                        "component_scores": {"structure_fit": 25},
                        "setup_score": 54,
                        "threshold": 62,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    records = load_strategy_diagnostics(reports_root)
    result = analyze_blocking_reasons(records)

    assert records[0]["blocking_reasons"] == ["STRUCTURE_BLOCK"]
    assert result["top_blocking_reasons"][0]["blocking_reason"] == "STRUCTURE_BLOCK"


def test_near_miss_uses_diagnostic_twenty_five_point_window() -> None:
    assert is_near_miss(setup_score=40, threshold=62, blocking_reasons=("ENSEMBLE_SCORE_LOW",), window=5)


def test_real_data_research_recommends_phase18_when_zero_trades(tmp_path: Path) -> None:
    config = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path), run_id="phase18-reco")
    runner = RealDataResearchRunner(config)
    runner._prepare_dirs()
    calibration_dir = runner.reports_dir / "calibration"
    calibration_dir.mkdir(parents=True)
    (calibration_dir / "summary.json").write_text(
        json.dumps({"recommended_profile": "BALANCED", "expected_signal_frequency": 12, "top_blocking_reasons": [{"blocking_reason": "score below threshold"}]}),
        encoding="utf-8",
    )
    results = [
        _stage("DATA_QUALITY", "PASSED", {"classification": "OK"}),
        _stage("BACKTEST", "WARNING", {"classification": "WARNING_NO_TRADES", "total_trades": 0}),
        _stage("BENCHMARK", "WARNING", {"classification": "NEEDS_MORE_DATA"}),
    ]

    compact = runner._compact_summary(results, "NEEDS_STRATEGY_RESEARCH", [], [])

    assert compact["likely_next_step"] == "Run FASE 19: Strategy Threshold Application / Balanced Profile Backtest."
    assert compact["calibration"]["recommended_profile"] == "BALANCED"
    assert compact["execution_attempted"] is False


def test_threshold_sweep_zero_signal_profiles_recommend_research_only(tmp_path: Path) -> None:
    report_dir = tmp_path / "calibration"

    summary = run_threshold_sweep_report(
        symbols=("EURUSD",),
        data_dir=tmp_path / "missing_historical",
        report_dir=report_dir,
        profiles_value="CONSERVATIVE,BALANCED,ACTIVE,RESEARCH_ONLY",
    )

    assert summary["recommended_profile"] == "RESEARCH_ONLY"
    assert summary["classification"] == "NEEDS_STRATEGY_RESEARCH"
    assert summary["signals_found"] == 0
    assert (report_dir / "near_misses.csv").exists()
    assert summary["execution_attempted"] is False


def test_latest_run_summary_includes_calibration_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "20260101-000000-real-data-research"
    calibration_dir = run_dir / "reports" / "calibration"
    calibration_dir.mkdir(parents=True)
    (run_dir / "final_summary_compact.json").write_text(
        json.dumps(
            {
                "run_id": "20260101-000000-real-data-research",
                "final_decision": "NEEDS_STRATEGY_RESEARCH",
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        ),
        encoding="utf-8",
    )
    (calibration_dir / "threshold_sweep_summary.json").write_text(
        json.dumps(
            {
                "classification": "NEEDS_STRATEGY_RESEARCH",
                "recommended_profile": "RESEARCH_ONLY",
                "signals_found": 0,
                "near_misses": 3,
                "top_blocking_reasons": [{"blocking_reason": "ENSEMBLE_SCORE_LOW", "count": 3}],
                "suggested_threshold_changes": {"next_step": "inspect data/feature generation"},
            }
        ),
        encoding="utf-8",
    )

    summary = load_latest_run_summary(tmp_path)

    assert summary["calibration_status"] == "NEEDS_STRATEGY_RESEARCH"
    assert summary["recommended_profile"] == "RESEARCH_ONLY"
    assert summary["near_misses"] == 3
    assert summary["top_blocking_reasons"][0]["blocking_reason"] == "ENSEMBLE_SCORE_LOW"


def _stage(name: str, status: str, summary: dict[str, object]):
    from agi_style_forex_bot_mt5.real_data_research import ResearchStageResult

    return ResearchStageResult(name=name, status=status, started_at_utc="", ended_at_utc="", duration_seconds=0.0, summary={**summary, "execution_attempted": False})


def _write_history(path: Path, *, rows: int) -> None:
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    data = []
    for index in range(rows):
        price = 1.1000 + (index % 30) * 0.00003
        data.append(
            {
                "time": (start + pd.Timedelta(minutes=5 * index)).isoformat(),
                "open": price,
                "high": price + 0.0002,
                "low": price - 0.0002,
                "close": price + (0.00005 if index % 2 == 0 else -0.00003),
                "tick_volume": 100 + index,
                "spread": 8 + index % 4,
            }
        )
    pd.DataFrame(data).to_csv(path, index=False)
