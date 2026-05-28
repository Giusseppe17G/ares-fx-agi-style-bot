from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.forward_evidence import run_forward_acceptance, run_forward_evidence
from agi_style_forex_bot_mt5.forward_evidence.operational_acceptance_gate import decide_operational_acceptance
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry_repair import run_quarantine_telemetry_issues, run_telemetry_drift_audit, run_telemetry_status
from agi_style_forex_bot_mt5.telemetry_repair.timestamp_issue_classifier import classify_timestamp_issue
from agi_style_forex_bot_mt5.telemetry_repair.timestamp_issue_loader import load_timestamp_issues


def test_historical_invalid_before_clean_window_is_auto_quarantine_candidate(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "SHADOW_MANUALLY_PAUSED", "timestamp_utc": "2026-05-25T00:00:00+00:00"})
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "ML_PREDICTION", "timestamp_utc": "2026-05-18T09:34:43.[REDACTED:9000]+00:00"})

    issues, context = load_timestamp_issues(log_dir=log_dir, reports_root=tmp_path / "reports")
    classified = [classify_timestamp_issue(issue, context, {}) for issue in issues]

    assert any(item["classification"] in {"HISTORICAL_AUTO_QUARANTINE_CANDIDATE", "REDACTED_TIMESTAMP_LEGACY"} for item in classified)
    status = run_telemetry_status(log_dir=log_dir, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    assert status["telemetry_acceptance_clear"] is True
    assert status["historical_unreviewed_count"] == 0


def test_derived_evidence_example_does_not_create_unreviewed_issue(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    forward = reports / "forward_evidence"
    forward.mkdir(parents=True)
    (forward / "evidence_summary.json").write_text(
        json.dumps({"invalid_timestamp_examples": ["2026-05-18T09:34:43.[REDACTED:9000]+00:00"]}),
        encoding="utf-8",
    )

    status = run_telemetry_status(log_dir=tmp_path / "logs", reports_root=reports, output_dir=tmp_path / "out")

    assert status["telemetry_status"] == "TELEMETRY_HISTORICAL_QUARANTINED"
    assert status["derived_example_count"] >= 1
    assert status["historical_unreviewed_count"] == 0


def test_heartbeat_count_is_not_timestamp_issue(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    forward = reports / "forward_evidence"
    forward.mkdir(parents=True)
    (forward / "evidence_summary.json").write_text(json.dumps({"heartbeat_count": 4200}), encoding="utf-8")

    status = run_telemetry_status(log_dir=tmp_path / "logs", reports_root=reports, output_dir=tmp_path / "out")

    assert status["telemetry_status"] == "TELEMETRY_CLEAN"
    assert status["historical_invalid_count"] == 0


def test_active_invalid_timestamp_still_blocks(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    prefix = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "HEARTBEAT", "timestamp_utc": f"{prefix}.[REDACTED:1234]+00:00"})

    status = run_telemetry_status(log_dir=log_dir, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")

    assert status["telemetry_status"] == "TELEMETRY_ACTIVE_BLOCKING"
    assert status["telemetry_acceptance_clear"] is False
    assert status["active_blocking_count"] >= 1


def test_quarantine_telemetry_issues_is_idempotent_for_drift(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    out = tmp_path / "out"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "SHADOW_MANUALLY_PAUSED", "timestamp_utc": "2026-05-25T00:00:00+00:00"})
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "ML_PREDICTION", "timestamp_utc": "2026-05-18T09:34:43.[REDACTED:9000]+00:00"})

    first = run_quarantine_telemetry_issues(log_dir=log_dir, reports_root=tmp_path / "reports", output_dir=out, reason="reviewed")
    second = run_quarantine_telemetry_issues(log_dir=log_dir, reports_root=tmp_path / "reports", output_dir=out, reason="reviewed again")

    assert first["newly_quarantined_count"] >= 1
    assert second["newly_quarantined_count"] == 0
    assert second["previously_quarantined_count"] >= 1
    assert second["unreviewed_count_after"] == 0


def test_forward_evidence_does_not_reintroduce_unreviewed_telemetry(tmp_path: Path) -> None:
    reports = _forward_reports(tmp_path)
    forward = reports / "forward_evidence"
    forward.mkdir(exist_ok=True)
    (forward / "evidence_summary.json").write_text(
        json.dumps({"invalid_timestamp_examples": ["2026-05-18T09:34:43.[REDACTED:9000]+00:00"]}),
        encoding="utf-8",
    )
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        db.insert_heartbeat({"timestamp_utc": "2026-05-25T00:00:00+00:00", "mode": "forward-shadow", "mt5_connected": True, "execution_attempted": False})
        summary = run_forward_evidence(database=db, log_dir=tmp_path / "logs", reports_root=reports, output_dir=forward)
    finally:
        db.close()

    assert summary["telemetry_acceptance_clear"] is True
    assert summary["historical_telemetry_unreviewed_count"] == 0
    assert summary["telemetry_drift_prevented"] is True


def test_forward_acceptance_does_not_return_telemetry_review_when_clear() -> None:
    decision = decide_operational_acceptance(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "hours_observed": 1},
        metrics={"paper_drawdown_status": "OK", "closed_trades": 0},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_HISTORICAL_QUARANTINED", "telemetry_acceptance_clear": True, "active_blocking_count": 0, "historical_unreviewed_count": 0},
    )

    assert decision["decision"] == "NEEDS_MORE_FORWARD_DATA"


def test_telemetry_drift_audit_cli(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "forward.sqlite3"
    db = TelemetryDatabase(sqlite)
    db.close()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "SHADOW_MANUALLY_PAUSED", "timestamp_utc": "2026-05-25T00:00:00+00:00"})
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "ML_PREDICTION", "timestamp_utc": "2026-05-18T09:34:43.[REDACTED:9000]+00:00"})

    assert cli.main(["--mode", "telemetry-drift-audit", "--sqlite", str(sqlite), "--log-dir", str(log_dir), "--reports-root", str(tmp_path / "reports"), "--telemetry-dir", str(tmp_path / "out"), "--output-dir", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["telemetry_drift_status"] == "TELEMETRY_DRIFT_CONTAINED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert (tmp_path / "out" / "telemetry_drift_summary.json").exists()


def _write_jsonl(path: Path, payload: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _forward_reports(root: Path) -> Path:
    reports = root / "reports"
    for name in ("stable_gate", "robustness", "execution_evidence", "paper_state", "paper_risk", "paper_risk_review", "paper_daily_risk", "paper_pnl_audit"):
        (reports / name).mkdir(parents=True, exist_ok=True)
    (reports / "stable_gate" / "stable_gate_summary.json").write_text(json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True}), encoding="utf-8")
    (reports / "paper_state" / "paper_state_report.json").write_text(json.dumps({"paper_trades_open": 0, "paper_drawdown": 0.0}), encoding="utf-8")
    (reports / "paper_pnl_audit" / "paper_pnl_scaling_check.json").write_text(json.dumps({"paper_pnl_scaling_status": "PAPER_PNL_SCALING_FIXED", "multiplier_application_ready": True}), encoding="utf-8")
    return reports
