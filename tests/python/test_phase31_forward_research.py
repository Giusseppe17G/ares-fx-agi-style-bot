from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.forward_diagnostics.forward_candidate_audit import audit_forward_candidate
from agi_style_forex_bot_mt5.forward_research import (
    analyze_ensemble_scores,
    load_forward_candidates,
    replay_candidates,
    run_blocker_sensitivity,
    run_forward_blocker_sensitivity,
    run_forward_candidate_replay,
)
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase


def _candidate(**overrides):
    payload = {
        "candidate_id": "cand-1",
        "timestamp_utc": "2026-05-18T12:00:00+00:00",
        "symbol": "EURUSD",
        "strategy_name": "strategy_ensemble",
        "session": "LONDON",
        "regime": "RANGE",
        "setup_score": 58.0,
        "ensemble_score": 55.0,
        "component_scores": {"regime_fit": 25.0, "momentum_fit": 65.0, "cost_fit": 80.0},
        "thresholds_used": {"ensemble_min_score": 60.0, "near_miss_window": 8.0},
        "blocking_reasons": ("REGIME_MISMATCH", "ENSEMBLE_SCORE_LOW"),
        "signal_profile": "BALANCED_STABLE",
        "stable_profile_hash": "hash",
        "spread_points": 10.0,
        "passed_thresholds": False,
        "execution_attempted": False,
    }
    payload.update(overrides)
    return payload


def test_candidate_loader_reads_mock_jsonl_events(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        audit_forward_candidate(
            database=db,
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            run_id="test",
            event_type="FORWARD_CANDIDATE_BLOCKED",
            payload=_candidate(),
            symbol="EURUSD",
        )
        loaded = load_forward_candidates(log_dir=tmp_path / "logs", diagnostics_dir=tmp_path / "diag")
        assert loaded.status == "OK"
        assert loaded.candidates[0]["symbol"] == "EURUSD"
        assert "REGIME_MISMATCH" in loaded.candidates[0]["blocking_reasons"]
    finally:
        db.close()


def test_candidate_replay_classifies_regime_mismatch() -> None:
    rows = replay_candidates([_candidate()])
    assert rows[0]["replay_decision"] == "BLOCK_CORRECT"
    assert "regime" in rows[0]["replay_reason"]
    assert rows[0]["execution_attempted"] is False


def test_ensemble_score_analyzer_detects_weak_component() -> None:
    analysis = analyze_ensemble_scores([_candidate()])
    assert analysis["top_score_drag_components"][0]["component"] == "regime_fit"
    assert analysis["candidates_close_to_threshold"] == 1


def test_blocker_sensitivity_generates_research_only_variants() -> None:
    summary, rows = run_blocker_sensitivity([_candidate()])
    assert summary["research_only"] is True
    assert summary["not_for_demo_live"] is True
    assert any(row["variant"] == "RELAX_REGIME_AND_SCORE_5" for row in rows)
    assert all(row["execution_attempted"] is False for row in rows)


def test_variants_do_not_modify_forward_sqlite(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        before = db.count_rows("events")
        diagnostics = tmp_path / "diag"
        diagnostics.mkdir()
        pd.DataFrame([_candidate()]).to_csv(diagnostics / "live_strategy_probe.csv", index=False)
        run_forward_blocker_sensitivity(diagnostics_dir=diagnostics, log_dir=tmp_path / "logs", output_dir=tmp_path / "out")
        after = db.count_rows("events")
        assert before == after
        assert (tmp_path / "out" / "blocker_sensitivity.json").exists()
    finally:
        db.close()


def test_forward_candidate_replay_cli_generates_reports(tmp_path: Path, capsys) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        audit_forward_candidate(
            database=db,
            audit_logger=JsonlAuditLogger(tmp_path / "logs"),
            run_id="test",
            event_type="FORWARD_CANDIDATE_BLOCKED",
            payload=_candidate(),
            symbol="EURUSD",
        )
    finally:
        db.close()
    code = cli.main([
        "--mode",
        "forward-candidate-replay",
        "--sqlite",
        str(tmp_path / "forward.sqlite3"),
        "--log-dir",
        str(tmp_path / "logs"),
        "--diagnostics-dir",
        str(tmp_path / "diag"),
        "--output-dir",
        str(tmp_path / "out"),
    ])
    assert code == 0
    output = capsys.readouterr().out
    assert '"mode": "forward-candidate-replay"' in output
    assert '"execution_attempted": false' in output
    assert (tmp_path / "out" / "candidate_replay_summary.json").exists()
    assert (tmp_path / "out" / "regime_mismatch_analysis.json").exists()


def test_forward_blocker_sensitivity_cli_generates_reports(tmp_path: Path, capsys) -> None:
    diagnostics = tmp_path / "diag"
    diagnostics.mkdir()
    pd.DataFrame([_candidate()]).to_csv(diagnostics / "live_strategy_probe.csv", index=False)
    code = cli.main([
        "--mode",
        "forward-blocker-sensitivity",
        "--diagnostics-dir",
        str(diagnostics),
        "--output-dir",
        str(tmp_path / "out"),
    ])
    assert code == 0
    output = capsys.readouterr().out
    assert '"mode": "forward-blocker-sensitivity"' in output
    assert '"execution_attempted": false' in output
    assert (tmp_path / "out" / "blocker_sensitivity.csv").exists()


def test_no_order_send_or_order_check_in_outputs(tmp_path: Path) -> None:
    diagnostics = tmp_path / "diag"
    diagnostics.mkdir()
    pd.DataFrame([_candidate()]).to_csv(diagnostics / "live_strategy_probe.csv", index=False)
    summary = run_forward_blocker_sensitivity(diagnostics_dir=diagnostics, log_dir=tmp_path / "logs", output_dir=tmp_path / "out")
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False
    assert summary["execution_attempted"] is False
