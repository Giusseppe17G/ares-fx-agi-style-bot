from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.forward_evidence.operational_acceptance_gate import decide_operational_acceptance
from agi_style_forex_bot_mt5.operational_readiness import run_operator_dashboard
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry_repair import run_quarantine_telemetry_issues, run_telemetry_acceptance_policy, run_telemetry_status, run_telemetry_timestamp_audit
from agi_style_forex_bot_mt5.telemetry_repair.timestamp_issue_loader import load_timestamp_issues
from agi_style_forex_bot_mt5.telemetry_repair.timestamp_issue_classifier import classify_timestamp_issue


def test_detects_redacted_timestamp(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "ML_PREDICTION", "timestamp_utc": "2026-05-18T09:34:43.[REDACTED:9000]+00:00"})

    issues, _context = load_timestamp_issues(log_dir=log_dir, reports_root=tmp_path / "reports")

    assert any("[REDACTED" in issue["raw_value"] for issue in issues)


def test_classifies_historical_invalid_timestamp(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "PAPER_TRADE_MANUAL_CLOSE", "timestamp_utc": "2026-05-25T00:00:00+00:00"})
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "ML_PREDICTION", "timestamp_utc": "2026-05-18T09:34:43.[REDACTED:9000]+00:00"})

    issues, context = load_timestamp_issues(log_dir=log_dir, reports_root=tmp_path / "reports")
    classified = [classify_timestamp_issue(issue, context, {}) for issue in issues]

    assert any(item["classification"] in {"HISTORICAL_TELEMETRY_INVALID", "REDACTED_TIMESTAMP"} for item in classified)


def test_classifies_recent_heartbeat_invalid_as_active(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "HEARTBEAT", "timestamp_utc": "2026-05-25T00:00:00.[REDACTED:1234]+00:00"})

    issues, context = load_timestamp_issues(log_dir=log_dir, reports_root=tmp_path / "reports")
    classified = [classify_timestamp_issue(issue, context, {}) for issue in issues]

    assert any(item["classification"] == "ACTIVE_TELEMETRY_INVALID" for item in classified)


def test_quarantine_does_not_modify_logs_and_skips_active(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    reports = tmp_path / "reports"
    log_dir.mkdir()
    log_path = log_dir / "events.jsonl"
    _write_jsonl(log_path, {"event_type": "PAPER_TRADE_MANUAL_CLOSE", "timestamp_utc": "2026-05-25T00:00:00+00:00"})
    _write_jsonl(log_path, {"event_type": "ML_PREDICTION", "timestamp_utc": "2026-05-18T09:34:43.[REDACTED:9000]+00:00"})
    original = log_path.read_text(encoding="utf-8")

    summary = run_quarantine_telemetry_issues(log_dir=log_dir, reports_root=reports, output_dir=tmp_path / "out", reason="reviewed")

    assert log_path.read_text(encoding="utf-8") == original
    assert summary["skipped_active_blocking"] == 0
    assert (tmp_path / "out" / "telemetry_quarantine_ledger.json").exists()


def test_quarantine_skips_active_issues(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "HEARTBEAT", "timestamp_utc": "2026-05-25T00:00:00.[REDACTED:1234]+00:00"})

    summary = run_quarantine_telemetry_issues(log_dir=log_dir, reports_root=tmp_path / "reports", output_dir=tmp_path / "out", reason="reviewed")

    assert summary["skipped_active_blocking"] >= 1
    assert summary["active_blocking_count"] >= 1


def test_telemetry_status_distinguishes_quarantined(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "PAPER_TRADE_MANUAL_CLOSE", "timestamp_utc": "2026-05-25T00:00:00+00:00"})
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "ML_PREDICTION", "timestamp_utc": "2026-05-18T09:34:43.[REDACTED:9000]+00:00"})

    run_quarantine_telemetry_issues(log_dir=log_dir, reports_root=tmp_path / "reports", output_dir=tmp_path / "out", reason="reviewed")
    status = run_telemetry_status(log_dir=log_dir, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")

    assert status["telemetry_acceptance_clear"] is True
    assert status["historical_quarantined_count"] >= 1
    assert status["telemetry_status"] == "TELEMETRY_HISTORICAL_QUARANTINED"
    assert status["historical_unreviewed_count"] == 0


def test_historical_quarantined_acceptance_policy_is_clear(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "PAPER_TRADE_MANUAL_CLOSE", "timestamp_utc": "2026-05-25T00:00:00+00:00"})
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "ML_PREDICTION", "timestamp_utc": "2026-05-18T09:34:43.[REDACTED:9000]+00:00"})

    run_quarantine_telemetry_issues(log_dir=log_dir, reports_root=tmp_path / "reports", output_dir=tmp_path / "out", reason="reviewed")
    policy = run_telemetry_acceptance_policy(log_dir=log_dir, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")

    assert policy["telemetry_acceptance_clear"] is True
    assert policy["telemetry_status"] == "TELEMETRY_HISTORICAL_QUARANTINED"
    assert policy["historical_invalid_count"] >= 1
    assert policy["quarantined_count"] >= policy["historical_invalid_count"]
    assert policy["unreviewed_count"] == 0


def test_forward_acceptance_does_not_block_quarantined_historical_timestamp() -> None:
    acceptance = decide_operational_acceptance(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "invalid_timestamp_count": 5, "hours_observed": 1},
        metrics={"paper_drawdown_status": "OK", "closed_trades": 0},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_HISTORICAL_QUARANTINED", "telemetry_acceptance_clear": True, "historical_invalid_count": 5, "quarantined_count": 5, "unknown_requires_review": 0},
    )
    assert acceptance["decision"] == "NEEDS_MORE_FORWARD_DATA"


def test_forward_acceptance_advances_with_legacy_status_when_counts_are_clear() -> None:
    acceptance = decide_operational_acceptance(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "invalid_timestamp_count": 5, "hours_observed": 1},
        metrics={"paper_drawdown_status": "OK", "closed_trades": 0},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_HISTORICAL_ISSUES_ONLY", "telemetry_acceptance_clear": True, "historical_invalid_count": 5, "quarantined_count": 5, "unknown_requires_review": 0},
    )
    assert acceptance["decision"] == "NEEDS_MORE_FORWARD_DATA"


def test_forward_acceptance_blocks_active_invalid_timestamp() -> None:
    acceptance = decide_operational_acceptance(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "hours_observed": 1},
        metrics={"paper_drawdown_status": "OK", "closed_trades": 0},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_ACTIVE_BLOCKING", "telemetry_acceptance_clear": False},
    )
    assert acceptance["decision"] == "NEEDS_TELEMETRY_FIX"


def test_unknown_timestamp_issue_blocks_policy() -> None:
    acceptance = decide_operational_acceptance(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "hours_observed": 1},
        metrics={"paper_drawdown_status": "OK", "closed_trades": 0},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_UNKNOWN_REVIEW_REQUIRED", "telemetry_acceptance_clear": False, "unknown_requires_review": 1},
    )
    assert acceptance["decision"] == "NEEDS_TELEMETRY_REVIEW"


def test_historical_unreviewed_issue_blocks_policy() -> None:
    acceptance = decide_operational_acceptance(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "hours_observed": 1},
        metrics={"paper_drawdown_status": "OK", "closed_trades": 0},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_HISTORICAL_ISSUES_ONLY", "telemetry_acceptance_clear": False, "historical_invalid_count": 5, "quarantined_count": 4, "unknown_requires_review": 0},
    )
    assert acceptance["decision"] == "NEEDS_TELEMETRY_REVIEW"


def test_telemetry_cli_modes_generate_reports(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "forward.sqlite3"
    db = TelemetryDatabase(sqlite)
    db.close()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "PAPER_TRADE_MANUAL_CLOSE", "timestamp_utc": "2026-05-25T00:00:00+00:00"})
    _write_jsonl(log_dir / "events.jsonl", {"event_type": "ML_PREDICTION", "timestamp_utc": "2026-05-18T09:34:43.[REDACTED:9000]+00:00"})

    assert cli.main(["--mode", "telemetry-timestamp-audit", "--sqlite", str(sqlite), "--log-dir", str(log_dir), "--reports-root", str(tmp_path / "reports"), "--output-dir", str(tmp_path / "out")]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["execution_attempted"] is False
    assert (tmp_path / "out" / "telemetry_timestamp_summary.json").exists()

    assert cli.main(["--mode", "quarantine-telemetry-issues", "--sqlite", str(sqlite), "--log-dir", str(log_dir), "--reports-root", str(tmp_path / "reports"), "--output-dir", str(tmp_path / "out"), "--reason", "reviewed"]) == 0
    quarantine = json.loads(capsys.readouterr().out)
    assert quarantine["execution_attempted"] is False

    assert cli.main(["--mode", "telemetry-status", "--sqlite", str(sqlite), "--log-dir", str(log_dir), "--reports-root", str(tmp_path / "reports"), "--output-dir", str(tmp_path / "out")]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["telemetry_acceptance_clear"] is True

    assert cli.main(["--mode", "telemetry-acceptance-policy", "--sqlite", str(sqlite), "--log-dir", str(log_dir), "--reports-root", str(tmp_path / "reports"), "--output-dir", str(tmp_path / "out")]) == 0
    policy = json.loads(capsys.readouterr().out)
    assert policy["telemetry_acceptance_clear"] is True
    assert policy["order_send_called"] is False


def test_dashboard_shows_telemetry_status(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _prepare_dashboard_reports(reports)
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        db.set_shadow_paused(True, reason="test", paused_by="test")
        summary = run_operator_dashboard(database=db, reports_root=reports, log_dir=tmp_path / "logs", output_dir=tmp_path / "dashboard", config=BotConfig())
    finally:
        db.close()

    assert summary["telemetry_status"] == "TELEMETRY_HISTORICAL_ISSUES_ONLY"
    assert summary["telemetry_acceptance_clear"] is True


def _write_jsonl(path: Path, payload: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _prepare_dashboard_reports(root: Path) -> None:
    for name in (
        "weekend_readiness",
        "ec2_readiness",
        "ec2_deployment_pack",
        "operator_drill",
        "paper_state",
        "forward_evidence",
        "forward_diagnostics",
        "stable_gate",
        "execution_evidence",
        "telemetry_repair",
    ):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "weekend_readiness" / "weekend_readiness_summary.json").write_text(json.dumps({"weekend_readiness_status": "WEEKEND_SAFE"}), encoding="utf-8")
    (root / "ec2_readiness" / "ec2_readiness_summary.json").write_text(json.dumps({"ec2_readiness_status": "EC2_READY_FOR_DRY_RUN"}), encoding="utf-8")
    (root / "ec2_deployment_pack" / "ec2_deployment_summary.json").write_text(json.dumps({"package_status": "EC2_DEPLOYMENT_PACK_READY"}), encoding="utf-8")
    (root / "ec2_deployment_pack" / "EC2_SECURITY_GUARDRAILS.md").write_text("DEMO_ONLY=True\nLIVE_TRADING_APPROVED=False\n", encoding="utf-8")
    (root / "operator_drill" / "operator_drill_summary.json").write_text(json.dumps({"operator_drill_status": "OPERATOR_DRILL_PASSED"}), encoding="utf-8")
    (root / "operator_drill" / "dry_run_market_open_summary.json").write_text(json.dumps({"dry_run_market_open_status": "DRY_RUN_MARKET_OPEN_READY"}), encoding="utf-8")
    (root / "paper_state" / "paper_state_report.json").write_text(json.dumps({"paper_trades_open": 0}), encoding="utf-8")
    (root / "forward_evidence" / "evidence_summary.json").write_text(json.dumps({"operational_acceptance": "NEEDS_MORE_FORWARD_DATA", "signals_detected": 0}), encoding="utf-8")
    (root / "forward_diagnostics" / "signal_scarcity_summary.json").write_text(json.dumps({"classification": "FORWARD_PIPELINE_OK_WAIT_FOR_SETUP"}), encoding="utf-8")
    (root / "stable_gate" / "stable_gate_summary.json").write_text(json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY"}), encoding="utf-8")
    (root / "execution_evidence" / "execution_evidence_summary.json").write_text(json.dumps({"execution_evidence_status": "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"}), encoding="utf-8")
    (root / "telemetry_repair" / "telemetry_timestamp_summary.json").write_text(
        json.dumps({"telemetry_status": "TELEMETRY_HISTORICAL_ISSUES_ONLY", "telemetry_acceptance_clear": True, "active_blocking_count": 0, "quarantined_count": 2}),
        encoding="utf-8",
    )
