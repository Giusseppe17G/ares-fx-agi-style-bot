from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.operational_readiness import (
    run_ec2_readiness_audit,
    run_market_open_checklist,
    run_weekend_readiness,
)
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def _prepare_reports(root: Path) -> None:
    for name in ("forward_evidence", "paper_state", "forward_diagnostics", "stable_gate", "stability_repair"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "stable_gate" / "stable_gate_summary.json").write_text(
        json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True}),
        encoding="utf-8",
    )
    (root / "stability_repair" / "balanced_stable.ini").write_text(
        "SIGNAL_PROFILE=BALANCED_STABLE\nAPPLY_STABILITY_FILTERS=true\nNOT_FOR_DEMO_LIVE=true\n",
        encoding="utf-8",
    )
    (root / "paper_state" / "paper_state_report.json").write_text(
        json.dumps({"paper_drawdown": 0, "paper_trades_open": 0}),
        encoding="utf-8",
    )


def _open_trade() -> dict[str, object]:
    return {
        "paper_trade_id": "ptr_weekend",
        "signal_id": "sig_weekend",
        "idempotency_key": "paper:ptr_weekend",
        "symbol": "EURUSD",
        "status": "OPEN",
        "entry_time_utc": "2026-05-18T09:30:00+00:00",
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
    }


def test_weekend_readiness_clean_sqlite_returns_weekend_safe(tmp_path: Path) -> None:
    sqlite = tmp_path / "forward.sqlite3"
    reports = tmp_path / "reports"
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    _prepare_reports(reports)
    db = TelemetryDatabase(sqlite)
    try:
        db.set_shadow_paused(True, reason="weekend pause", paused_by="test")
    finally:
        db.close()

    summary = run_weekend_readiness(sqlite_path=sqlite, log_dir=logs, reports_root=reports, output_dir=tmp_path / "out", config=BotConfig())

    assert summary["weekend_readiness_status"] == "WEEKEND_SAFE"
    assert summary["paper_clean_state"] is True
    assert summary["execution_attempted"] is False
    assert (tmp_path / "out" / "weekend_readiness_summary.json").exists()
    assert (tmp_path / "out" / "checks.csv").exists()


def test_weekend_readiness_detects_open_paper_trades(tmp_path: Path) -> None:
    sqlite = tmp_path / "forward.sqlite3"
    reports = tmp_path / "reports"
    _prepare_reports(reports)
    db = TelemetryDatabase(sqlite)
    try:
        db.set_shadow_paused(True, reason="weekend pause", paused_by="test")
        db.insert_paper_trade(_open_trade())
    finally:
        db.close()

    summary = run_weekend_readiness(sqlite_path=sqlite, log_dir=tmp_path / "logs", reports_root=reports, output_dir=tmp_path / "out", config=BotConfig())

    assert summary["weekend_readiness_status"] == "NEEDS_PAPER_STATE_REVIEW"
    assert summary["paper_trades_open"] == 1
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_market_open_checklist_generates_commands(tmp_path: Path) -> None:
    summary = run_market_open_checklist(
        sqlite_path=tmp_path / "forward.sqlite3",
        reports_root=tmp_path / "reports",
        output_dir=tmp_path / "checklist",
        symbols="EURUSD,GBPUSD,USDJPY",
    )

    commands = (tmp_path / "checklist" / "commands.ps1").read_text(encoding="utf-8")
    assert summary["execution_attempted"] is False
    assert "--mode mt5-diagnose" in commands
    assert "--mode forward-shadow" in commands
    assert "LIVE_TRADING_APPROVED=False" in commands


def test_ec2_readiness_audit_detects_missing_scripts(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("data/logs/\ndata/sqlite/\ndata/reports/\n*.sqlite3\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("EC2 PYTHONPATH DEMO_ONLY=True LIVE_TRADING_APPROVED=False", encoding="utf-8")

    summary = run_ec2_readiness_audit(reports_root=tmp_path / "reports", output_dir=tmp_path / "out", project_root=tmp_path)

    assert summary["ec2_readiness_status"] == "EC2_NEEDS_SCRIPT_REPAIR"
    assert summary["execution_attempted"] is False


def test_ec2_readiness_audit_detects_possible_secrets_mock(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for script in (
        "run_forward_shadow_balanced_stable.ps1",
        "watchdog_forward_shadow_balanced_stable.ps1",
        "status_forward_shadow_stable.ps1",
        "daily_summary_stable.ps1",
    ):
        (scripts / script).write_text("$env:PYTHONPATH='src/python'\n# BALANCED_STABLE\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("data/logs/\ndata/sqlite/\ndata/reports/\n*.sqlite3\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "README.md").write_text("EC2 PYTHONPATH DEMO_ONLY=True LIVE_TRADING_APPROVED=False", encoding="utf-8")
    (docs / "DEPLOY_WINDOWS_EC2.md").write_text("EC2 PYTHONPATH DEMO_ONLY=True LIVE_TRADING_APPROVED=False", encoding="utf-8")
    (tmp_path / "config.ini").write_text("TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWX\n", encoding="utf-8")

    summary = run_ec2_readiness_audit(reports_root=tmp_path / "reports", output_dir=tmp_path / "out", project_root=tmp_path)

    assert summary["ec2_readiness_status"] == "EC2_NEEDS_SECRET_REVIEW"
    assert summary["secret_findings_count"] >= 1
    assert summary["execution_attempted"] is False
