from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.operational_readiness import run_dry_run_market_open, run_operator_drill
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def _prepare_reports(root: Path) -> None:
    for name in ("weekend_readiness", "ec2_deployment_pack", "market_open_checklist", "stable_gate", "stability_repair"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "weekend_readiness" / "weekend_readiness_summary.json").write_text(
        json.dumps({"weekend_readiness_status": "WEEKEND_SAFE", "paper_clean_state": True, "paper_trades_open": 0}),
        encoding="utf-8",
    )
    (root / "ec2_deployment_pack" / "ec2_deployment_summary.json").write_text(
        json.dumps({"package_status": "EC2_DEPLOYMENT_PACK_READY"}),
        encoding="utf-8",
    )
    (root / "ec2_deployment_pack" / "EC2_COMMANDS.ps1").write_text(
        "DEMO_ONLY=True\nLIVE_TRADING_APPROVED=False\n--mode forward-shadow\n",
        encoding="utf-8",
    )
    (root / "market_open_checklist" / "commands.ps1").write_text(
        "--mode mt5-diagnose\n--mode live-feature-contract\n--mode forward-shadow\n",
        encoding="utf-8",
    )
    (root / "stable_gate" / "stable_gate_summary.json").write_text(
        json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True}),
        encoding="utf-8",
    )
    (root / "stability_repair" / "balanced_stable.ini").write_text(
        "SIGNAL_PROFILE=BALANCED_STABLE\nAPPLY_STABILITY_FILTERS=true\n",
        encoding="utf-8",
    )


def _clean_paused_db(path: Path) -> None:
    db = TelemetryDatabase(path)
    try:
        db.set_shadow_paused(True, reason="weekend", paused_by="test")
    finally:
        db.close()


def _open_trade() -> dict[str, object]:
    return {
        "paper_trade_id": "ptr_drill",
        "signal_id": "sig_drill",
        "idempotency_key": "paper:ptr_drill",
        "symbol": "EURUSD",
        "status": "OPEN",
        "entry_time_utc": "2026-05-18T09:30:00+00:00",
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
    }


def test_operator_drill_generates_reports(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _prepare_reports(reports)

    summary = run_operator_drill(reports_root=reports, output_dir=tmp_path / "out", config=BotConfig())

    assert summary["classification"] == "OPERATOR_DRILL_PASSED"
    assert summary["execution_attempted"] is False
    assert (tmp_path / "out" / "operator_drill_summary.json").exists()
    assert (tmp_path / "out" / "operator_steps.csv").exists()
    assert (tmp_path / "out" / "failure_scenarios.csv").exists()
    assert (tmp_path / "out" / "market_open_commands_review.md").exists()
    assert (tmp_path / "out" / "report.html").exists()


def test_dry_run_market_open_passes_with_clean_paper_state(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    sqlite = tmp_path / "forward.sqlite3"
    _prepare_reports(reports)
    _clean_paused_db(sqlite)

    summary = run_dry_run_market_open(sqlite_path=sqlite, reports_root=reports, output_dir=tmp_path / "out", config=BotConfig())

    assert summary["classification"] == "DRY_RUN_MARKET_OPEN_READY"
    assert summary["paper_trades_open"] == 0
    assert summary["paper_shadow_paused"] is True
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_dry_run_market_open_blocks_with_open_paper_trades(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    sqlite = tmp_path / "forward.sqlite3"
    _prepare_reports(reports)
    db = TelemetryDatabase(sqlite)
    try:
        db.set_shadow_paused(True, reason="weekend", paused_by="test")
        db.insert_paper_trade(_open_trade())
    finally:
        db.close()

    summary = run_dry_run_market_open(sqlite_path=sqlite, reports_root=reports, output_dir=tmp_path / "out", config=BotConfig())

    assert summary["classification"] == "DRY_RUN_MARKET_OPEN_BLOCKED"
    assert summary["paper_trades_open"] == 1


def test_dry_run_market_open_blocks_when_stable_gate_missing(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    sqlite = tmp_path / "forward.sqlite3"
    _prepare_reports(reports)
    (reports / "stable_gate" / "stable_gate_summary.json").unlink()
    _clean_paused_db(sqlite)

    summary = run_dry_run_market_open(sqlite_path=sqlite, reports_root=reports, output_dir=tmp_path / "out", config=BotConfig())

    assert summary["classification"] == "DRY_RUN_MARKET_OPEN_BLOCKED"
    assert any(check["check_name"] == "stable_gate_exists" and check["status"] == "FAIL" for check in summary["checks"])


def test_failure_scenarios_contain_recommended_actions(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _prepare_reports(reports)

    run_operator_drill(reports_root=reports, output_dir=tmp_path / "out", config=BotConfig())
    scenarios = (tmp_path / "out" / "failure_scenarios.csv").read_text(encoding="utf-8")

    assert "MT5_DISCONNECTED" in scenarios
    assert "FEATURE_PIPELINE_NOT_READY" in scenarios
    assert "recommended_action" in scenarios
    assert "order_send" not in scenarios
