from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.paper_daily_risk_state import run_paper_daily_risk_audit, run_paper_daily_risk_clear, run_paper_legacy_drawdown_audit
from agi_style_forex_bot_mt5.paper_risk_calibration import run_paper_risk_status
from agi_style_forex_bot_mt5.paper_risk_review.clearance_ledger import append_clearance
from agi_style_forex_bot_mt5.paper_daily_risk_state.daily_risk_ledger import append_daily_risk_clearance
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def _micro_ini(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "SIGNAL_PROFILE=BALANCED_STABLE_MICRO",
                "PROFILE_TYPE=PAPER_SHADOW_ONLY",
                "PAPER_ONLY=true",
                "NOT_FOR_DEMO_LIVE=true",
                "PAPER_RISK_MULTIPLIER=0.1",
                "paper_risk_multiplier=0.1",
                "MAX_OPEN_PAPER_TRADES=1",
                "MAX_PAPER_TRADES_PER_DAY=2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _ready_reports(root: Path) -> tuple[Path, Path, Path, Path]:
    reports = root / "reports"
    paper_risk = reports / "paper_risk"
    pnl = reports / "paper_pnl_audit"
    stable = reports / "stable_gate"
    execution = reports / "execution_evidence"
    telemetry = reports / "telemetry_repair"
    for path in (paper_risk, pnl, stable, execution, telemetry, reports / "paper_state"):
        path.mkdir(parents=True, exist_ok=True)
    _micro_ini(paper_risk / "balanced_stable_micro.ini")
    pnl.joinpath("paper_pnl_scaling_check.json").write_text(json.dumps({"paper_pnl_scaling_status": "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS", "legacy_unscaled_trade_count": 1, "scaled_trade_count": 0, "created_at_utc": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    pnl.joinpath("paper_pnl_audit_summary.json").write_text(json.dumps({"paper_pnl_audit_status": "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS", "current_engine_multiplier_ready": True, "legacy_unscaled_events": True}), encoding="utf-8")
    stable.joinpath("stable_gate_summary.json").write_text(json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True, "execution_attempted": False}), encoding="utf-8")
    execution.joinpath("execution_evidence_summary.json").write_text(json.dumps({"execution_evidence_status": "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY", "blocking_findings_count": 0}), encoding="utf-8")
    telemetry.joinpath("telemetry_timestamp_summary.json").write_text(json.dumps({"telemetry_status": "TELEMETRY_CLEAN", "telemetry_acceptance_clear": True}), encoding="utf-8")
    (reports / "paper_state" / "paper_state_report.json").write_text(json.dumps({"paper_trades_open": 0, "paper_drawdown": -100.0, "daily_drawdown_limit": -3.0, "drawdown_basis": "SCALED_PAPER_PNL_ONLY"}), encoding="utf-8")
    logs = root / "logs"
    logs.mkdir()
    return reports, paper_risk, pnl, logs


def _halt(db: TelemetryDatabase, when: datetime, *, scaled: bool = False, invalid: bool = False) -> None:
    payload: dict[str, object] = {
        "alert_code": "PAPER_DAILY_DRAWDOWN",
        "severity": "CRITICAL",
        "timestamp_utc": "[REDACTED:9000]" if invalid else when.isoformat(),
        "deduplication_key": f"halt-{when.timestamp()}-{scaled}-{invalid}",
    }
    if scaled:
        payload.update({"drawdown_basis": "SCALED_PAPER_PNL", "scaled_drawdown": -5.0})
    else:
        payload.update({"drawdown_basis": "LEGACY_UNSCALED_PNL", "raw_drawdown": -50.0})
    db.insert_alert(payload, dedup_window_seconds=0)


def _ledgers(root: Path, halt_time: datetime, clearance_time_offset_seconds: int = 5) -> tuple[str, str]:
    review = root / "review"
    daily = root / "daily"
    clearance = append_clearance(output_dir=review, reason="reviewed", latest_halt_utc=halt_time.isoformat())
    daily_entry = append_daily_risk_clearance(
        output_dir=daily,
        reason="daily reviewed",
        latest_halt_utc=halt_time.isoformat(),
        latest_clearance_utc=clearance["created_at_utc"],
        clearance_id=clearance["clearance_id"],
        operational_day=datetime.now(timezone.utc).date().isoformat(),
    )
    return clearance["ledger_path"], daily_entry["ledger_path"]


def test_legacy_unscaled_event_before_pnl_fix_does_not_trigger_active_halt(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, pnl, logs = _ready_reports(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _halt(db, old, scaled=False)
    clearance, daily = _ledgers(tmp_path, old)
    try:
        summary = run_paper_legacy_drawdown_audit(database=db, log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, pnl_audit_dir=pnl, clearance_ledger=clearance, daily_risk_ledger=daily, profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=reports / "paper_daily_risk")
        assert summary["legacy_drawdown_status"] == "LEGACY_DRAWDOWN_QUARANTINED"
        assert summary["active_scaled_events_count"] == 0
        assert summary["can_resume_micro_shadow"] is True
    finally:
        db.close()


def test_legacy_event_before_daily_ledger_does_not_trigger_active_halt(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, pnl, logs = _ready_reports(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _halt(db, old, scaled=False)
    clearance, daily = _ledgers(tmp_path, old)
    try:
        audit = run_paper_daily_risk_audit(database=db, log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance, daily_risk_ledger=daily, profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=reports / "paper_daily_risk")
        assert audit["paper_daily_risk_status"] == "LEGACY_DRAWDOWN_QUARANTINED"
        assert audit["active_today_halt_count"] == 0
        assert audit["can_resume_micro_shadow"] is True
    finally:
        db.close()


def test_invalid_timestamp_legacy_does_not_trigger_active_halt(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, pnl, logs = _ready_reports(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _halt(db, old, invalid=True)
    clearance, daily = _ledgers(tmp_path, old)
    try:
        summary = run_paper_legacy_drawdown_audit(database=db, log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, pnl_audit_dir=pnl, clearance_ledger=clearance, daily_risk_ledger=daily, profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=reports / "paper_daily_risk")
        assert summary["invalid_timestamp_halt_count"] >= 1
        assert summary["active_scaled_events_count"] == 0
    finally:
        db.close()


def test_active_scaled_event_after_ledger_blocks(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, _, logs = _ready_reports(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _halt(db, old, scaled=False)
    clearance, daily = _ledgers(tmp_path, old)
    _halt(db, datetime.now(timezone.utc) + timedelta(seconds=5), scaled=True)
    try:
        audit = run_paper_daily_risk_audit(database=db, log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance, daily_risk_ledger=daily, profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=reports / "paper_daily_risk")
        assert audit["paper_daily_risk_status"] == "ACTIVE_DRAWDOWN_HALT"
        assert audit["can_resume_micro_shadow"] is False
    finally:
        db.close()


def test_paper_daily_risk_clear_grants_ledger_for_legacy_only(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, _, logs = _ready_reports(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _halt(db, old, scaled=False)
    clearance, _daily = _ledgers(tmp_path, old)
    try:
        summary = run_paper_daily_risk_clear(database=db, reason="legacy reviewed", log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance, profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=reports / "paper_daily_risk")
        assert summary["classification"] == "PAPER_DAILY_RISK_CLEARANCE_GRANTED"
        assert summary["legacy_drawdown_quarantined"] is True
    finally:
        db.close()


def test_paper_risk_status_allows_micro_when_only_legacy_quarantined(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, _, logs = _ready_reports(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _halt(db, old, scaled=False)
    clearance, daily = _ledgers(tmp_path, old)
    db.set_shadow_paused(True, reason="PAPER_DAILY_DRAWDOWN_HALT", paused_by="test")
    try:
        status = run_paper_risk_status(database=db, profile_config=paper_risk / "balanced_stable_micro.ini", clearance_ledger=clearance, daily_risk_ledger=daily, log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, output_dir=reports / "paper_risk")
        assert status["paper_risk_status"] == "PAPER_RISK_CLEAR_FOR_MICRO_SHADOW"
        assert status["blocking_reason"] == ""
        assert status["legacy_drawdown_quarantined"] is True
    finally:
        db.close()


def test_cli_mode_exists_and_generates_report(tmp_path: Path, capsys) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, pnl, logs = _ready_reports(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _halt(db, old, scaled=False)
    clearance, daily = _ledgers(tmp_path, old)
    db.close()
    assert cli.main(["--mode", "paper-legacy-drawdown-audit", "--sqlite", str(tmp_path / "paper.sqlite3"), "--log-dir", str(logs), "--reports-root", str(reports), "--paper-risk-dir", str(paper_risk), "--pnl-audit-dir", str(pnl), "--clearance-ledger", str(clearance), "--daily-risk-ledger", str(daily), "--profile-config", str(paper_risk / "balanced_stable_micro.ini"), "--output-dir", str(reports / "paper_daily_risk")]) == 0
    out = capsys.readouterr().out
    assert '"mode": "paper-legacy-drawdown-audit"' in out
    assert '"execution_attempted": false' in out
    assert (reports / "paper_daily_risk" / "legacy_drawdown_audit_summary.json").exists()


def test_forward_shadow_micro_preflight_accepts_legacy_quarantined(tmp_path: Path, monkeypatch, capsys) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, _, logs = _ready_reports(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _halt(db, old, scaled=False)
    clearance, daily = _ledgers(tmp_path, old)
    db.set_shadow_paused(True, reason="PAPER_DAILY_DRAWDOWN_HALT", paused_by="test")
    db.close()

    class FakeForwardShadowBot:
        def __init__(self, **kwargs):
            pass

        def run(self):
            return SimpleNamespace(mode="forward-shadow", mt5_connected=False, cycles_completed=0, open_trades=0, paper_trades_opened=0, paper_trades_closed=0, heartbeat_written=False, alerts_emitted=0, telegram_commands_processed=0, shadow_paused=False, execution_attempted=False, signal_profile_used="BALANCED_STABLE_MICRO", stable_gate_confirmed=True, order_send_called=False, order_check_called=False, exit_reason="", halt_reason="", paper_shadow_paused=False, critical_alerts_recent=(), next_recommended_command="")

    monkeypatch.setattr(cli, "ForwardShadowBot", FakeForwardShadowBot)
    assert cli.main(["--mode", "forward-shadow", "--sqlite", str(tmp_path / "paper.sqlite3"), "--log-dir", str(logs), "--reports-root", str(reports), "--paper-risk-dir", str(paper_risk), "--signal-profile", "BALANCED_STABLE_MICRO", "--profile-config", str(paper_risk / "balanced_stable_micro.ini"), "--stable-gate", str(reports / "stable_gate" / "stable_gate_summary.json"), "--paper-risk-clearance", str(clearance), "--daily-risk-ledger", str(daily), "--max-cycles", "0"]) == 0
    out = capsys.readouterr().out
    assert '"signal_profile_used": "BALANCED_STABLE_MICRO"' in out
    assert '"order_send_called": false' in out


def test_forward_shadow_micro_blocks_active_scaled_drawdown(tmp_path: Path, capsys) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, _, logs = _ready_reports(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _halt(db, old, scaled=False)
    clearance, daily = _ledgers(tmp_path, old)
    _halt(db, datetime.now(timezone.utc) + timedelta(seconds=5), scaled=True)
    db.close()
    assert cli.main(["--mode", "forward-shadow", "--sqlite", str(tmp_path / "paper.sqlite3"), "--log-dir", str(logs), "--reports-root", str(reports), "--paper-risk-dir", str(paper_risk), "--signal-profile", "BALANCED_STABLE_MICRO", "--profile-config", str(paper_risk / "balanced_stable_micro.ini"), "--stable-gate", str(reports / "stable_gate" / "stable_gate_summary.json"), "--paper-risk-clearance", str(clearance), "--daily-risk-ledger", str(daily), "--max-cycles", "0"]) == 0
    out = capsys.readouterr().out
    assert "PAPER_DRAWDOWN_HALT_BLOCK" in out or "ACTIVE_DRAWDOWN_HALT" in out
    assert '"execution_attempted": false' in out
