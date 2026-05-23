from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.operational_readiness import run_daily_operator_report, run_operator_dashboard
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter


def _prepare_reports(root: Path) -> None:
    for name in (
        "weekend_readiness",
        "ec2_readiness",
        "ec2_deployment_pack",
        "operator_drill",
        "paper_state",
        "forward_evidence",
        "forward_diagnostics",
        "stable_gate",
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
    (root / "forward_diagnostics" / "signal_scarcity_summary.json").write_text(json.dumps({"classification": "FORWARD_PIPELINE_OK_WAIT_FOR_SETUP", "top_blockers": [{"blocking_reason": "NO_SETUP_DETECTED", "count": 1}]}), encoding="utf-8")
    (root / "stable_gate" / "stable_gate_summary.json").write_text(json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY"}), encoding="utf-8")


def _clean_db(path: Path) -> TelemetryDatabase:
    db = TelemetryDatabase(path)
    db.set_shadow_paused(True, reason="weekend", paused_by="test")
    return db


def _open_trade() -> dict[str, object]:
    return {
        "paper_trade_id": "ptr_dash",
        "signal_id": "sig_dash",
        "idempotency_key": "paper:ptr_dash",
        "symbol": "EURUSD",
        "status": "OPEN",
        "entry_time_utc": "2026-05-18T09:30:00+00:00",
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
    }


def test_operator_dashboard_generates_json_csv_html(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _prepare_reports(reports)
    db = _clean_db(tmp_path / "forward.sqlite3")
    try:
        summary = run_operator_dashboard(database=db, reports_root=reports, log_dir=tmp_path / "logs", output_dir=tmp_path / "dashboard", config=BotConfig())
    finally:
        db.close()

    assert summary["classification"] == "OPERATOR_DASHBOARD_OK"
    assert summary["paper_shadow_paused"] is True
    assert summary["execution_attempted"] is False
    assert (tmp_path / "dashboard" / "operator_dashboard_summary.json").exists()
    assert (tmp_path / "dashboard" / "operator_dashboard_checks.csv").exists()
    assert (tmp_path / "dashboard" / "dashboard.html").exists()


def test_daily_operator_report_generates_json_md_ps1(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _prepare_reports(reports)
    db = _clean_db(tmp_path / "forward.sqlite3")
    try:
        summary = run_daily_operator_report(database=db, reports_root=reports, log_dir=tmp_path / "logs", output_dir=tmp_path / "daily", config=BotConfig())
    finally:
        db.close()

    commands = (tmp_path / "daily" / "next_commands.ps1").read_text(encoding="utf-8")
    assert summary["classification"] == "DAILY_REPORT_OK"
    assert (tmp_path / "daily" / "daily_operator_report.json").exists()
    assert (tmp_path / "daily" / "daily_operator_report.md").exists()
    assert "LIVE_TRADING_APPROVED=True" not in commands
    assert "DEMO_ONLY=False" not in commands
    assert "order_send" not in commands
    assert "order_check" not in commands


def test_dashboard_works_with_missing_optional_reports(tmp_path: Path) -> None:
    db = _clean_db(tmp_path / "forward.sqlite3")
    try:
        summary = run_operator_dashboard(database=db, reports_root=tmp_path / "missing_reports", log_dir=tmp_path / "logs", output_dir=tmp_path / "dashboard", config=BotConfig())
    finally:
        db.close()

    assert summary["classification"] in {"OPERATOR_DASHBOARD_NEEDS_REVIEW", "OPERATOR_DASHBOARD_BLOCKED"}
    assert summary["execution_attempted"] is False
    assert (tmp_path / "dashboard" / "dashboard.html").exists()


def test_dashboard_detects_open_paper_trades_as_needs_review(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _prepare_reports(reports)
    db = _clean_db(tmp_path / "forward.sqlite3")
    try:
        db.insert_paper_trade(_open_trade())
        summary = run_operator_dashboard(database=db, reports_root=reports, log_dir=tmp_path / "logs", output_dir=tmp_path / "dashboard", config=BotConfig())
    finally:
        db.close()

    assert summary["classification"] == "OPERATOR_DASHBOARD_NEEDS_REVIEW"
    assert summary["paper_trades_open"] == 1


def test_telegram_dashboard_daily_next_action_are_read_only(tmp_path: Path) -> None:
    reports = Path("data/reports/operator_dashboard")
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "operator_dashboard_summary.json").write_text(json.dumps({"recommended_next_action": "Review offline dashboard", "execution_attempted": False}), encoding="utf-8")
    db = _clean_db(tmp_path / "forward.sqlite3")
    try:
        center = TelegramCommandCenter(database=db, allowed_chat_id="1", bot_token="")
        for command in ("/dashboard", "/daily_report", "/next_action"):
            result = center.process_update({"message": {"chat": {"id": "1"}, "text": command}})
            assert result.accepted is True
            assert result.execution_attempted is False
    finally:
        db.close()
