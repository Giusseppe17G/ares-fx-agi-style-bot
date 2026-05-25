from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.paper_daily_risk_state import run_paper_daily_risk_clear
from agi_style_forex_bot_mt5.paper_risk_calibration import run_paper_risk_status
from agi_style_forex_bot_mt5.paper_risk_review import normalize_profile_name, run_paper_risk_clearance, run_paper_risk_clearance_check, run_paper_risk_review, validate_micro_resume_clearance
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
        "profit": -1.0 if status == "CLOSED" else 0.0,
        "r_multiple": -1.0 if status == "CLOSED" else 0.0,
        "exit_time_utc": now if status == "CLOSED" else None,
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


def _ready_reports(root: Path, *, execution_status: str = "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY", telemetry_status: str = "TELEMETRY_CLEAN", telemetry_clear: bool = True) -> None:
    (root / "stable_gate").mkdir(parents=True, exist_ok=True)
    (root / "stable_gate" / "stable_gate_summary.json").write_text('{"stable_gate_decision":"PAPER_SHADOW_READY","paper_shadow_ready":true,"execution_attempted":false}', encoding="utf-8")
    (root / "execution_evidence").mkdir(parents=True, exist_ok=True)
    (root / "execution_evidence" / "execution_evidence_summary.json").write_text(
        json.dumps({"execution_evidence_status": execution_status, "blocking_findings_count": 0 if "BLOCKED" not in execution_status else 1}),
        encoding="utf-8",
    )
    (root / "telemetry_repair").mkdir(parents=True, exist_ok=True)
    (root / "telemetry_repair" / "telemetry_timestamp_summary.json").write_text(
        json.dumps({"telemetry_status": telemetry_status, "telemetry_acceptance_clear": telemetry_clear}),
        encoding="utf-8",
    )
    (root / "paper_state").mkdir(parents=True, exist_ok=True)
    (root / "paper_state" / "paper_state_report.json").write_text(json.dumps({"paper_trades_open": 0, "paper_drawdown": 0.0}), encoding="utf-8")


def _halt(db: TelemetryDatabase, when: datetime | None = None) -> str:
    timestamp = (when or datetime.now(timezone.utc)).isoformat()
    db.insert_alert({"alert_code": "PAPER_DAILY_DRAWDOWN", "severity": "CRITICAL", "deduplication_key": f"dd-{timestamp}", "timestamp_utc": timestamp}, dedup_window_seconds=0)
    db.set_shadow_paused(True, reason="PAPER_DAILY_DRAWDOWN_HALT", paused_by="test")
    return timestamp


def _ready_context(tmp_path: Path) -> tuple[TelemetryDatabase, Path, Path, str]:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    halt_time = _halt(db)
    reports = tmp_path / "reports"
    _ready_reports(reports)
    paper_risk = reports / "paper_risk"
    _micro_ini(paper_risk / "balanced_stable_micro.ini")
    return db, reports, paper_risk, halt_time


def test_paper_risk_review_detects_halt_and_open_trades_zero(tmp_path: Path) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    try:
        summary = run_paper_risk_review(database=db, log_dir=tmp_path / "logs", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
        assert summary["classification"] == "PAPER_RISK_REVIEW_READY_FOR_CLEARANCE"
        assert summary["paper_trades_open"] == 0
        assert summary["latest_halt_utc"]
    finally:
        db.close()


def test_paper_risk_clearance_fails_without_reason(tmp_path: Path) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    try:
        summary = run_paper_risk_clearance(database=db, reason="", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
        assert summary["classification"] == "PAPER_RISK_CLEARANCE_DENIED_NO_REASON"
    finally:
        db.close()


def test_paper_risk_clearance_fails_with_open_trades(tmp_path: Path) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    try:
        db.insert_paper_trade(_trade("ptr_open"))
        summary = run_paper_risk_clearance(database=db, reason="reviewed", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
        assert summary["classification"] == "PAPER_RISK_CLEARANCE_DENIED_OPEN_TRADES"
    finally:
        db.close()


def test_paper_risk_clearance_fails_execution_and_telemetry_blocks(tmp_path: Path) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    try:
        _ready_reports(reports, execution_status="EXECUTION_EVIDENCE_BLOCKED_REAL_ATTEMPT")
        summary = run_paper_risk_clearance(database=db, reason="reviewed", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
        assert summary["classification"] == "PAPER_RISK_CLEARANCE_DENIED_EXECUTION_EVIDENCE"
        _ready_reports(reports, telemetry_status="TELEMETRY_ACTIVE_BLOCKING", telemetry_clear=False)
        summary = run_paper_risk_clearance(database=db, reason="reviewed", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review2")
        assert summary["classification"] == "PAPER_RISK_CLEARANCE_DENIED_TELEMETRY"
    finally:
        db.close()


def test_paper_risk_clearance_passes_with_clean_evidence_and_micro_profile(tmp_path: Path) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    try:
        summary = run_paper_risk_clearance(database=db, reason="Manual review after halt", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
        assert summary["classification"] == "PAPER_RISK_CLEARANCE_GRANTED"
        assert summary["cleared_for_profile"] == "BALANCED_STABLE_MICRO"
        assert (tmp_path / "review" / "paper_risk_clearance_ledger.json").exists()
    finally:
        db.close()


def test_profile_name_normalization_and_path_inference(tmp_path: Path) -> None:
    assert normalize_profile_name("BALANCED_STABLE_MICRO") == "BALANCED_STABLE_MICRO"
    assert normalize_profile_name("balanced_stable_micro") == "BALANCED_STABLE_MICRO"
    assert normalize_profile_name("Balanced Stable Micro") == "BALANCED_STABLE_MICRO"

    inferred_ini = tmp_path / "balanced_stable_micro.ini"
    inferred_ini.write_text("PAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\n", encoding="utf-8")
    check = run_paper_risk_clearance_check(profile_config=inferred_ini, clearance_ledger=tmp_path / "missing.json", output_dir=tmp_path / "check")
    assert check["requested_profile_canonical"] == "BALANCED_STABLE_MICRO"
    assert "PROFILE_INFERRED_FROM_CONFIG_PATH" in check["profile_warnings"]


def test_paper_risk_status_allows_micro_only_with_valid_clearance(tmp_path: Path) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    try:
        granted = run_paper_risk_clearance(database=db, reason="reviewed", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
        blocked = run_paper_risk_status(database=db, profile_config=paper_risk / "balanced_stable_micro.ini", clearance_ledger=granted["ledger_path"], reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "risk_blocked")
        assert blocked["paper_risk_status"] == "PAPER_RISK_BLOCKED"
        assert blocked["paper_daily_risk_status"] == "PAPER_DAILY_RISK_LEDGER_REQUIRED"
        daily = run_paper_daily_risk_clear(
            database=db,
            reason="Clear stale halt after review",
            reports_root=reports,
            paper_risk_dir=paper_risk,
            clearance_ledger=granted["ledger_path"],
            profile_config=paper_risk / "balanced_stable_micro.ini",
            output_dir=tmp_path / "daily",
        )
        status = run_paper_risk_status(database=db, profile_config=paper_risk / "balanced_stable_micro.ini", clearance_ledger=granted["ledger_path"], daily_risk_ledger=daily["ledger_path"], reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "risk")
        assert status["paper_risk_status"] == "PAPER_RISK_CLEAR_FOR_MICRO_SHADOW"
        assert status["daily_drawdown_status"] == "CLEARED_STALE_HALT"
        assert status["can_open_new_paper_trade"] is True
        normal = run_paper_risk_status(database=db, profile_config=paper_risk / "balanced_stable_micro.ini", clearance_ledger=granted["ledger_path"], profile_name="BALANCED_STABLE", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "risk2")
        assert normal["can_open_new_paper_trade"] is False
        assert normal["blocking_reason"] == "PAPER_DRAWDOWN_HALT_BLOCK"
    finally:
        db.close()


def test_paper_risk_clearance_check_matches_micro_and_rejects_normal(tmp_path: Path) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    try:
        granted = run_paper_risk_clearance(database=db, reason="reviewed", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
        check = run_paper_risk_clearance_check(
            profile="balanced stable micro",
            profile_config=paper_risk / "balanced_stable_micro.ini",
            clearance_ledger=granted["ledger_path"],
            output_dir=tmp_path / "check",
        )
        assert check["clearance_match"] is True
        assert check["requested_profile_canonical"] == "BALANCED_STABLE_MICRO"
        assert check["cleared_for_profile_canonical"] == "BALANCED_STABLE_MICRO"

        normal = run_paper_risk_clearance_check(
            profile="BALANCED_STABLE",
            profile_config=paper_risk / "balanced_stable_micro.ini",
            clearance_ledger=granted["ledger_path"],
            output_dir=tmp_path / "check_normal",
        )
        assert normal["clearance_match"] is False
        assert normal["mismatch_reason"] == "REQUESTED_PROFILE_NOT_MICRO"
    finally:
        db.close()


def test_paper_risk_clearance_check_cli_generates_match(tmp_path: Path, capsys) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    try:
        granted = run_paper_risk_clearance(database=db, reason="reviewed", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
        assert (
            cli.main(
                [
                    "--mode",
                    "paper-risk-clearance-check",
                    "--profile",
                    "BALANCED_STABLE_MICRO",
                    "--profile-config",
                    str(paper_risk / "balanced_stable_micro.ini"),
                    "--clearance-ledger",
                    str(granted["ledger_path"]),
                    "--output-dir",
                    str(tmp_path / "check_cli"),
                ]
            )
            == 0
        )
        out = capsys.readouterr().out
        assert '"clearance_match": true' in out
        assert '"execution_attempted": false' in out
    finally:
        db.close()


def test_paper_risk_status_infers_micro_from_config_when_cli_profile_default(tmp_path: Path, capsys) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    try:
        granted = run_paper_risk_clearance(database=db, reason="reviewed", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
        daily = run_paper_daily_risk_clear(
            database=db,
            reason="Clear stale halt after review",
            reports_root=reports,
            paper_risk_dir=paper_risk,
            clearance_ledger=granted["ledger_path"],
            profile_config=paper_risk / "balanced_stable_micro.ini",
            output_dir=tmp_path / "daily",
        )
        assert (
            cli.main(
                [
                    "--mode",
                    "paper-risk-status",
                    "--sqlite",
                    str(tmp_path / "forward.sqlite3"),
                    "--profile-config",
                    str(paper_risk / "balanced_stable_micro.ini"),
                    "--clearance-ledger",
                    str(granted["ledger_path"]),
                    "--daily-risk-ledger",
                    str(daily["ledger_path"]),
                    "--reports-root",
                    str(reports),
                    "--paper-risk-dir",
                    str(paper_risk),
                    "--output-dir",
                    str(tmp_path / "risk_cli"),
                ]
            )
            == 0
        )
        out = capsys.readouterr().out
        assert '"paper_risk_status": "PAPER_RISK_CLEAR_FOR_MICRO_SHADOW"' in out
        assert '"paper_risk_clearance_status": "PAPER_RISK_CLEARANCE_ACCEPTED"' in out
    finally:
        db.close()


def test_forward_shadow_micro_fails_without_or_stale_clearance(tmp_path: Path, capsys) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    sqlite = tmp_path / "forward.sqlite3"
    db.close()
    args = [
        "--mode",
        "forward-shadow",
        "--sqlite",
        str(sqlite),
        "--signal-profile",
        "BALANCED_STABLE_MICRO",
        "--profile-config",
        str(paper_risk / "balanced_stable_micro.ini"),
        "--stable-gate",
        str(reports / "stable_gate" / "stable_gate_summary.json"),
        "--paper-risk-dir",
        str(paper_risk),
        "--reports-root",
        str(reports),
        "--max-cycles",
        "0",
    ]
    assert cli.main(args) == 0
    assert "PAPER_RISK_CLEARANCE_REQUIRED" in capsys.readouterr().out
    stale = tmp_path / "stale.json"
    stale.write_text(
        json.dumps({"clearances": [{"clearance_id": "old", "created_at_utc": "2026-01-01T00:00:00+00:00", "cleared_for_profile": "BALANCED_STABLE_MICRO"}]}),
        encoding="utf-8",
    )
    assert cli.main([*args, "--paper-risk-clearance", str(stale)]) == 0
    assert "PAPER_RISK_CLEARANCE_STALE" in capsys.readouterr().out


def test_forward_shadow_micro_accepts_valid_clearance_without_live_run(tmp_path: Path, capsys, monkeypatch) -> None:
    db, reports, paper_risk, _ = _ready_context(tmp_path)
    granted = run_paper_risk_clearance(database=db, reason="reviewed", reports_root=reports, paper_risk_dir=paper_risk, output_dir=tmp_path / "review")
    daily = run_paper_daily_risk_clear(
        database=db,
        reason="Clear stale halt after review",
        reports_root=reports,
        paper_risk_dir=paper_risk,
        clearance_ledger=granted["ledger_path"],
        profile_config=paper_risk / "balanced_stable_micro.ini",
        output_dir=tmp_path / "daily",
    )
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
                "--signal-profile",
                "BALANCED_STABLE_MICRO",
                "--profile-config",
                str(paper_risk / "balanced_stable_micro.ini"),
                "--stable-gate",
                str(reports / "stable_gate" / "stable_gate_summary.json"),
                "--paper-risk-clearance",
                str(granted["ledger_path"]),
                "--daily-risk-ledger",
                str(daily["ledger_path"]),
                "--paper-risk-dir",
                str(paper_risk),
                "--reports-root",
                str(reports),
                "--max-cycles",
                "0",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert '"signal_profile_used": "BALANCED_STABLE_MICRO"' in out
    assert '"execution_attempted": false' in out
