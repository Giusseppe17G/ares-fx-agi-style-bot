from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.calibration import profile_allowed_for_shadow, write_profile_comparison
from agi_style_forex_bot_mt5.profile_validation import (
    build_profile_threshold_diff,
    compare_profile_metrics,
    run_balanced_candidate_gate,
    run_profile_integrity,
)
from agi_style_forex_bot_mt5.real_data_research import load_latest_run_summary


def test_profile_threshold_diff_detects_identical_thresholds() -> None:
    summary = build_profile_threshold_diff()

    assert summary["profile_similarity_status"] == "IDENTICAL_THRESHOLDS"
    assert any(pair["left"] == "BALANCED" and pair["right"] == "BALANCED_FILTERED" for pair in summary["identical_pairs"])
    assert summary["execution_attempted"] is False


def test_profile_metric_comparator_detects_identical_metrics(tmp_path: Path) -> None:
    _write_profile_comparison(
        tmp_path,
        balanced={"trades_generated": 213, "signals_generated": 217, "winrate": 46.48, "expectancy_r": 0.197, "profit_factor": 2.75, "max_drawdown_pct": 5.0},
        active={"trades_generated": 213, "signals_generated": 217, "winrate": 46.48, "expectancy_r": 0.197, "profit_factor": 2.75, "max_drawdown_pct": 5.0},
    )

    summary = compare_profile_metrics(tmp_path)

    assert summary["metric_similarity_status"] == "IDENTICAL_METRICS"
    assert "profile thresholds not applied" in summary["comparisons"][0]["possible_causes"]


def test_profile_comparison_run_saves_thresholds_and_hash(tmp_path: Path, capsys) -> None:
    output = tmp_path / "profiles"

    assert cli.main(["--mode", "profile-comparison-run", "--symbols", "EURUSD", "--data-dir", str(tmp_path / "historical"), "--output-dir", str(output), "--compare-profiles", "BALANCED,ACTIVE"]) == 0
    payload = json.loads(capsys.readouterr().out)
    comparison = json.loads((output / "profile_comparison.json").read_text(encoding="utf-8"))
    balanced = next(row for row in comparison["profiles"] if row["profile"] == "BALANCED")

    assert payload["execution_attempted"] is False
    assert "thresholds_used" in balanced
    assert balanced["profile_hash"]


def test_balanced_gate_positive_metrics_needs_robustness_validation(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile_runs"
    _write_profile_comparison(
        profile_dir,
        balanced={"trades_generated": 213, "signals_generated": 217, "sample_status": "USABLE_SAMPLE", "metrics_status": "FULL_EDGE_METRICS", "winrate": 46.48, "expectancy_r": 0.197, "profit_factor": 2.75, "max_drawdown_pct": 5.0},
        active={"trades_generated": 260, "signals_generated": 270, "sample_status": "USABLE_SAMPLE", "metrics_status": "FULL_EDGE_METRICS", "winrate": 45.0, "expectancy_r": 0.12, "profit_factor": 1.5, "max_drawdown_pct": 6.0},
    )
    edge_dir = tmp_path / "edge"
    edge_dir.mkdir()
    (edge_dir / "edge_summary.json").write_text(json.dumps({"decision": "TEST_ACTIVE_RESEARCH_ONLY", "metrics_status": "FULL_EDGE_METRICS"}), encoding="utf-8")

    summary = run_balanced_candidate_gate(runs_root=tmp_path / "runs", profile_runs_dir=profile_dir, edge_dir=edge_dir, output_dir=tmp_path / "validation")

    assert summary["balanced_decision"] == "BALANCED_NEEDS_ROBUSTNESS_VALIDATION"
    assert summary["execution_attempted"] is False


def test_balanced_gate_integrity_failure_is_untrusted(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile_runs"
    _write_profile_comparison(
        profile_dir,
        balanced={"trades_generated": 213, "signals_generated": 217, "sample_status": "USABLE_SAMPLE", "metrics_status": "FULL_EDGE_METRICS", "winrate": 46.48, "expectancy_r": 0.197, "profit_factor": 2.75, "max_drawdown_pct": 5.0},
        active={"trades_generated": 213, "signals_generated": 217, "sample_status": "USABLE_SAMPLE", "metrics_status": "FULL_EDGE_METRICS", "winrate": 46.48, "expectancy_r": 0.197, "profit_factor": 2.75, "max_drawdown_pct": 5.0},
    )
    edge_dir = tmp_path / "edge"
    edge_dir.mkdir()
    (edge_dir / "edge_summary.json").write_text("{}", encoding="utf-8")

    summary = run_balanced_candidate_gate(runs_root=tmp_path / "runs", profile_runs_dir=profile_dir, edge_dir=edge_dir, output_dir=tmp_path / "validation")

    assert summary["balanced_decision"] == "BALANCED_METRICS_UNTRUSTED"


def test_active_never_allowed_for_shadow() -> None:
    assert profile_allowed_for_shadow("ACTIVE") is False


def test_cli_accepts_profile_integrity_and_balanced_gate(tmp_path: Path, capsys) -> None:
    profile_dir = tmp_path / "profile_runs"
    _write_profile_comparison(
        profile_dir,
        balanced={"trades_generated": 120, "signals_generated": 130, "sample_status": "USABLE_SAMPLE", "metrics_status": "FULL_EDGE_METRICS", "winrate": 50.0, "expectancy_r": 0.1, "profit_factor": 1.3, "max_drawdown_pct": 3.0},
        active={"trades_generated": 150, "signals_generated": 160, "sample_status": "USABLE_SAMPLE", "metrics_status": "FULL_EDGE_METRICS", "winrate": 48.0, "expectancy_r": 0.08, "profit_factor": 1.2, "max_drawdown_pct": 4.0},
    )
    edge_dir = tmp_path / "edge"
    edge_dir.mkdir()
    (edge_dir / "edge_summary.json").write_text("{}", encoding="utf-8")

    assert cli.main(["--mode", "profile-integrity", "--profile-runs-dir", str(profile_dir), "--output-dir", str(tmp_path / "validation")]) == 0
    integrity = json.loads(capsys.readouterr().out)
    assert integrity["mode"] == "profile-integrity"

    assert cli.main(["--mode", "balanced-candidate-gate", "--runs-root", str(tmp_path / "runs"), "--profile-runs-dir", str(profile_dir), "--edge-dir", str(edge_dir), "--output-dir", str(tmp_path / "validation")]) == 0
    gate = json.loads(capsys.readouterr().out)
    assert gate["mode"] == "balanced-candidate-gate"
    assert gate["execution_attempted"] is False


def test_latest_run_summary_includes_profile_validation(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "20260517-160651-real-data-research"
    validation = run / "reports" / "profile_validation"
    validation.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "execution_attempted": False}), encoding="utf-8")
    (validation / "profile_integrity.json").write_text(json.dumps({"profile_integrity_status": "FAILED", "active_vs_balanced_similarity": "IDENTICAL_METRICS"}), encoding="utf-8")
    (validation / "balanced_candidate_gate.json").write_text(json.dumps({"balanced_decision": "BALANCED_METRICS_UNTRUSTED", "reason": "duplicated metrics"}), encoding="utf-8")

    summary = load_latest_run_summary(tmp_path / "runs")

    assert summary["profile_integrity_status"] == "FAILED"
    assert summary["active_vs_balanced_similarity"] == "IDENTICAL_METRICS"
    assert summary["balanced_candidate_decision"] == "BALANCED_METRICS_UNTRUSTED"


def _write_profile_comparison(profile_dir: Path, *, balanced: dict[str, object], active: dict[str, object]) -> None:
    metrics = {
        "BALANCED": balanced,
        "ACTIVE": active,
    }
    write_profile_comparison(profile_dir, metrics)
