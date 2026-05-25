from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.paper_daily_risk_state import run_paper_daily_risk_audit, run_paper_daily_risk_clear
from agi_style_forex_bot_mt5.paper_risk_calibration import run_paper_risk_status
from agi_style_forex_bot_mt5.paper_risk_review import run_paper_risk_clearance
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def _trade(trade_id: str, status: str = "OPEN") -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig_{trade_id}",
        "idempotency_key": f"paper:{trade_id}",
        "symbol": "EURUSD",
        "status": status,
        "entry_time_utc": now,
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
        "profit": 0.0,
        "r_multiple": 0.0,
        "strategy_name": "strategy_ensemble",
        "metadata": {},
    }


def _micro_ini(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "SIGNAL_PROFILE=BALANCED_STABLE_MICRO",
                "PROFILE_TYPE=PAPER_SHADOW_ONLY",
                "PAPER_ONLY=true",
                "NOT_FOR_DEMO_LIVE=true",
                "STABILITY_FILTERS_APPLIED=true",
                "PAPER_RISK_MULTIPLIER=0.10",
                "MAX_OPEN_PAPER_TRADES=1",
                "MAX_PAPER_TRADES_PER_DAY=2",
                "COOLDOWN_AFTER_LOSS_MINUTES=0",
                "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES=1440",
                "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT=true",
                "MANUAL_RESUME_REQUIRED=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _ready_reports(root: Path) -> None:
    (root / "stable_gate").mkdir(parents=True, exist_ok=True)
    (root / "stable_gate" / "stable_gate_summary.json").write_text('{"stable_gate_decision":"PAPER_SHADOW_READY","paper_shadow_ready":true,"execution_attempted":false}', encoding="utf-8")
    (root / "execution_evidence").mkdir(parents=True, exist_ok=True)
    (root / "execution_evidence" / "execution_evidence_summary.json").write_text('{"execution_evidence_status":"EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY","blocking_findings_count":0}', encoding="utf-8")
    (root / "telemetry_repair").mkdir(parents=True, exist_ok=True)
    (root / "telemetry_repair" / "telemetry_timestamp_summary.json").write_text('{"telemetry_status":"TELEMETRY_CLEAN","telemetry_acceptance_clear":true}', encoding="utf-8")
    (root / "paper_state").mkdir(parents=True, exist_ok=True)
    (root / "paper_state" / "paper_state_report.json").write_text('{"paper_trades_open":0,"paper_drawdown":0.0}', encoding="utf-8")


def _halt(db: TelemetryDatabase, when: datetime | None = None) -> str:
    timestamp = (when or datetime.now(timezone.utc)).isoformat()
    db.insert_alert({"alert_code": "PAPER_DAILY_DRAWDOWN", "severity": "CRITICAL", "deduplication_key": f"dd-{timestamp}", "timestamp_utc": timestamp}, dedup_window_seconds=0)
    db.set_shadow_paused(True, reason="PAPER_DAILY_DRAWDOWN_HALT", paused_by="test")
    return timestamp


def _ready_context(tmp_path: Path) -> tuple[TelemetryDatabase, Path, Path, Path, dict[str, object]]:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    _halt(db)
    reports = tmp_path / "reports"
    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    _ready_reports(reports)
    paper_risk = reports / "paper_risk"
    _micro_ini(paper_risk / "balanced_stable_micro.ini")
    clearance = run_paper_risk_clearance(database=db, reason="reviewed", log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
    return db, reports, paper_risk, logs, clearance


def test_halt_before_clearance_classifies_as_stale(tmp_path: Path) -> None:
    db, reports, paper_risk, logs, clearance = _ready_context(tmp_path)
    try:
        summary = run_paper_daily_risk_audit(database=db, log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance["ledger_path"], profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=tmp_path / "daily")
        assert summary["stale_halt_count"] >= 1
        rows = (tmp_path / "daily" / "drawdown_halt_classification.csv").read_text(encoding="utf-8")
        assert "STALE_HALT_BEFORE_CLEARANCE" in rows
    finally:
        db.close()


def test_halt_after_clearance_blocks(tmp_path: Path) -> None:
    db, reports, paper_risk, logs, clearance = _ready_context(tmp_path)
    try:
        _halt(db, datetime.now(timezone.utc) + timedelta(seconds=5))
        summary = run_paper_daily_risk_audit(database=db, log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance["ledger_path"], profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=tmp_path / "daily")
        assert summary["active_today_halt_count"] >= 1
        assert summary["can_resume_micro_shadow"] is False
    finally:
        db.close()


def test_invalid_timestamp_halt_is_reported_without_contaminating_active_day(tmp_path: Path) -> None:
    db, reports, paper_risk, logs, clearance = _ready_context(tmp_path)
    try:
        bad_log = logs / "bad.jsonl"
        bad_log.write_text(json.dumps({"event_type": "PAPER_SHADOW_HALTED", "timestamp_utc": "[REDACTED:9000]"}) + "\n", encoding="utf-8")
        summary = run_paper_daily_risk_audit(database=db, log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance["ledger_path"], profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=tmp_path / "daily")
        assert summary["invalid_timestamp_halt_count"] >= 1
        assert summary["active_today_halt_count"] == 0
    finally:
        db.close()


def test_paper_daily_risk_clear_requires_reason_and_open_trades_zero(tmp_path: Path) -> None:
    db, reports, paper_risk, logs, clearance = _ready_context(tmp_path)
    try:
        no_reason = run_paper_daily_risk_clear(database=db, reason="", log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance["ledger_path"], profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=tmp_path / "daily")
        assert no_reason["classification"] == "PAPER_DAILY_RISK_CLEAR_DENIED_NO_REASON"
        db.insert_paper_trade(_trade("open"))
        blocked = run_paper_daily_risk_clear(database=db, reason="reviewed", log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance["ledger_path"], profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=tmp_path / "daily2")
        assert blocked["classification"] == "PAPER_DAILY_RISK_CLEAR_DENIED_OPEN_TRADES"
    finally:
        db.close()


def test_paper_daily_risk_clear_and_status_allow_micro(tmp_path: Path) -> None:
    db, reports, paper_risk, logs, clearance = _ready_context(tmp_path)
    try:
        daily = run_paper_daily_risk_clear(database=db, reason="Clear stale paper drawdown halt after review", log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance["ledger_path"], profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=tmp_path / "daily")
        assert daily["classification"] == "PAPER_DAILY_RISK_CLEARANCE_GRANTED"
        status = run_paper_risk_status(database=db, profile_config=paper_risk / "balanced_stable_micro.ini", clearance_ledger=clearance["ledger_path"], daily_risk_ledger=daily["ledger_path"], log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "risk")
        assert status["paper_risk_status"] == "PAPER_RISK_CLEAR_FOR_MICRO_SHADOW"
        assert status["daily_drawdown_status"] == "CLEARED_STALE_HALT"
        assert status["can_open_new_paper_trade"] is True
    finally:
        db.close()


def test_forward_shadow_micro_requires_daily_ledger_for_stale_halt(tmp_path: Path, capsys) -> None:
    db, reports, paper_risk, logs, clearance = _ready_context(tmp_path)
    db.close()
    assert (
        cli.main(
            [
                "--mode",
                "forward-shadow",
                "--sqlite",
                str(tmp_path / "forward.sqlite3"),
                "--log-dir",
                str(logs),
                "--reports-root",
                str(reports),
                "--paper-risk-dir",
                str(paper_risk),
                "--signal-profile",
                "BALANCED_STABLE_MICRO",
                "--profile-config",
                str(paper_risk / "balanced_stable_micro.ini"),
                "--stable-gate",
                str(reports / "stable_gate" / "stable_gate_summary.json"),
                "--paper-risk-clearance",
                str(clearance["ledger_path"]),
                "--max-cycles",
                "0",
            ]
        )
        == 0
    )
    assert "PAPER_DAILY_RISK_LEDGER_REQUIRED" in capsys.readouterr().out


def test_forward_shadow_micro_accepts_clearance_and_daily_ledger(tmp_path: Path, capsys, monkeypatch) -> None:
    db, reports, paper_risk, logs, clearance = _ready_context(tmp_path)
    daily = run_paper_daily_risk_clear(database=db, reason="Clear stale paper drawdown halt after review", log_dir=logs, reports_root=reports, paper_risk_dir=paper_risk, clearance_ledger=clearance["ledger_path"], profile_config=paper_risk / "balanced_stable_micro.ini", output_dir=tmp_path / "daily")
    db.close()

    class FakeForwardShadowBot:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def run(self):
            return SimpleNamespace(
                mode="forward-shadow",
                mt5_connected=False,
                cycles_completed=0,
                open_trades=0,
                paper_trades_opened=0,
                paper_trades_closed=0,
                execution_attempted=False,
                order_send_called=False,
                order_check_called=False,
                signal_profile_used="BALANCED_STABLE_MICRO",
            )

    monkeypatch.setattr(cli, "ForwardShadowBot", FakeForwardShadowBot)
    assert (
        cli.main(
            [
                "--mode",
                "forward-shadow",
                "--sqlite",
                str(tmp_path / "forward.sqlite3"),
                "--log-dir",
                str(logs),
                "--reports-root",
                str(reports),
                "--paper-risk-dir",
                str(paper_risk),
                "--signal-profile",
                "BALANCED_STABLE_MICRO",
                "--profile-config",
                str(paper_risk / "balanced_stable_micro.ini"),
                "--stable-gate",
                str(reports / "stable_gate" / "stable_gate_summary.json"),
                "--paper-risk-clearance",
                str(clearance["ledger_path"]),
                "--daily-risk-ledger",
                str(daily["ledger_path"]),
                "--max-cycles",
                "0",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert '"signal_profile_used": "BALANCED_STABLE_MICRO"' in out
    assert '"execution_attempted": false' in out
