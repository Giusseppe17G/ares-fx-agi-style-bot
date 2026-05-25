from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.paper_pnl_audit import run_paper_pnl_audit, run_paper_risk_recommendation
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def _trade(
    trade_id: str,
    *,
    entry: float = 1.1000,
    exit_price: float = 1.0990,
    profit: float = -100.0,
    direction: str = "BUY",
    symbol: str = "EURUSD",
    strategy: str = "trend_pullback",
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    opened = opened_at or (now - timedelta(minutes=20))
    closed = closed_at or (now - timedelta(minutes=5))
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig_{trade_id}",
        "idempotency_key": f"paper:{trade_id}",
        "symbol": symbol,
        "status": "CLOSED",
        "entry_time_utc": opened.isoformat(),
        "exit_time_utc": closed.isoformat(),
        "entry_price": entry,
        "exit_price": exit_price,
        "sl_price": entry - 0.0010 if direction.upper() == "BUY" else entry + 0.0010,
        "tp_price": entry + 0.0020 if direction.upper() == "BUY" else entry - 0.0020,
        "direction": direction,
        "lot": 1.0,
        "profit": profit,
        "r_multiple": profit / 100.0,
        "strategy_name": strategy,
        "commission_assumed": 0.0,
        "metadata": metadata or {"profile": "BALANCED_STABLE_MICRO", "paper_risk_multiplier": 0.1},
    }


def _micro_ini(path: Path, multiplier: float = 0.1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "SIGNAL_PROFILE=BALANCED_STABLE_MICRO",
                "PAPER_ONLY=true",
                "NOT_FOR_DEMO_LIVE=true",
                f"PAPER_RISK_MULTIPLIER={multiplier}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _reports(root: Path, *, clearance: datetime | None = None, limit: float = -3.0) -> tuple[Path, Path, Path]:
    reports = root / "reports"
    paper_risk = reports / "paper_risk"
    daily = reports / "paper_daily_risk"
    state = reports / "paper_state"
    paper_risk.mkdir(parents=True, exist_ok=True)
    daily.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    state.joinpath("paper_state_report.json").write_text(json.dumps({"paper_drawdown": -100.0, "daily_drawdown_limit": limit}), encoding="utf-8")
    payload = {"active_today_halt_count": 1, "daily_paper_drawdown": -100.0}
    if clearance is not None:
        payload["latest_clearance_utc"] = clearance.isoformat()
    daily.joinpath("paper_daily_risk_summary.json").write_text(json.dumps(payload), encoding="utf-8")
    return reports, paper_risk, daily


def _halt(db: TelemetryDatabase, when: datetime | None = None) -> None:
    timestamp = (when or datetime.now(timezone.utc)).isoformat()
    db.insert_alert({"alert_code": "PAPER_DAILY_DRAWDOWN", "severity": "CRITICAL", "timestamp_utc": timestamp, "deduplication_key": f"halt-{timestamp}"}, dedup_window_seconds=0)


def test_detects_micro_multiplier_not_applied(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, daily = _reports(tmp_path)
    config = _micro_ini(paper_risk / "balanced_stable_micro.ini", 0.1)
    try:
        db.insert_paper_trade(_trade("micro_unscaled", profit=-100.0, metadata={"profile": "BALANCED_STABLE_MICRO", "paper_risk_multiplier": 0.1}))
        _halt(db)
        summary = run_paper_pnl_audit(database=db, reports_root=reports, paper_risk_dir=paper_risk, daily_risk_dir=daily, profile_config=config, output_dir=tmp_path / "audit")
        assert summary["paper_pnl_audit_status"] == "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"
        assert summary["root_cause"] == "LEGACY_UNSCALED_PNL"
    finally:
        db.close()


def test_detects_risk_multiplier_not_applied(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, daily = _reports(tmp_path)
    config = _micro_ini(paper_risk / "balanced_stable_micro.ini", 1.0)
    try:
        db.insert_paper_trade(_trade("risk_unscaled", profit=-100.0, metadata={"profile": "BALANCED_STABLE_MICRO", "risk_multiplier": 0.25}))
        _halt(db)
        summary = run_paper_pnl_audit(database=db, reports_root=reports, paper_risk_dir=paper_risk, daily_risk_dir=daily, profile_config=config, output_dir=tmp_path / "audit")
        assert summary["paper_pnl_audit_status"] == "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"
        assert summary["root_cause"] == "LEGACY_UNSCALED_PNL"
    finally:
        db.close()


def test_detects_pnl_sign_error(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, daily = _reports(tmp_path)
    config = _micro_ini(paper_risk / "balanced_stable_micro.ini", 1.0)
    try:
        db.insert_paper_trade(_trade("sign_error", entry=1.1000, exit_price=1.1010, profit=-100.0, metadata={"profile": "BALANCED_STABLE_MICRO"}))
        _halt(db)
        summary = run_paper_pnl_audit(database=db, reports_root=reports, paper_risk_dir=paper_risk, daily_risk_dir=daily, profile_config=config, output_dir=tmp_path / "audit")
        assert summary["paper_pnl_audit_status"] == "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"
        assert summary["root_cause"] == "LEGACY_UNSCALED_PNL"
    finally:
        db.close()


def test_detects_drawdown_history_leak(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    clearance = datetime.now(timezone.utc)
    reports, paper_risk, daily = _reports(tmp_path, clearance=clearance)
    config = _micro_ini(paper_risk / "balanced_stable_micro.ini", 0.1)
    try:
        db.insert_paper_trade(_trade("old_loss", closed_at=clearance - timedelta(minutes=10), profit=-10.0, metadata={"profile": "BALANCED_STABLE_MICRO", "paper_risk_multiplier": 0.1}))
        _halt(db, clearance + timedelta(minutes=1))
        summary = run_paper_pnl_audit(database=db, reports_root=reports, paper_risk_dir=paper_risk, daily_risk_dir=daily, profile_config=config, output_dir=tmp_path / "audit")
        assert summary["paper_pnl_audit_status"] == "DRAWDOWN_HISTORY_LEAK"
        assert summary["recommended_action"] == "READY_FOR_NEW_MICRO_CLEARANCE"
    finally:
        db.close()


def test_detects_drawdown_threshold_unit_mismatch(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, daily = _reports(tmp_path, limit=-3.0)
    config = _micro_ini(paper_risk / "balanced_stable_micro.ini", 1.0)
    try:
        db.insert_paper_trade(_trade("unit_mismatch", profit=-50.0, metadata={"profile": "BALANCED_STABLE_MICRO"}))
        _halt(db)
        summary = run_paper_pnl_audit(database=db, reports_root=reports, paper_risk_dir=paper_risk, daily_risk_dir=daily, profile_config=config, output_dir=tmp_path / "audit")
        assert summary["paper_pnl_audit_status"] == "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"
        assert summary["legacy_unscaled_events"] is True
    finally:
        db.close()


def test_classifies_valid_micro_drawdown_halt(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, daily = _reports(tmp_path, limit=-3.0)
    config = _micro_ini(paper_risk / "balanced_stable_micro.ini", 0.1)
    try:
        db.insert_paper_trade(_trade("valid_micro_loss", profit=-10.0, metadata={"profile": "BALANCED_STABLE_MICRO", "paper_risk_multiplier": 0.1}))
        _halt(db)
        summary = run_paper_pnl_audit(database=db, reports_root=reports, paper_risk_dir=paper_risk, daily_risk_dir=daily, profile_config=config, output_dir=tmp_path / "audit")
        assert summary["paper_pnl_audit_status"] == "PAPER_PNL_SCALING_PARTIAL_LEGACY_EVENTS"
        assert summary["recommended_action"] == "READY_FOR_NEW_MICRO_CLEARANCE"
    finally:
        db.close()


def test_paper_risk_recommendation_blocks_scaling_bug_and_valid_halt(tmp_path: Path) -> None:
    audit_dir = tmp_path / "reports" / "paper_pnl_audit"
    audit_dir.mkdir(parents=True)
    audit_dir.joinpath("paper_pnl_audit_summary.json").write_text(json.dumps({"paper_pnl_audit_status": "PAPER_PNL_SCALING_BUG", "root_cause": "PNL_SIGN_ERROR"}), encoding="utf-8")
    scaling = run_paper_risk_recommendation(reports_root=tmp_path / "reports", pnl_audit_dir=audit_dir, output_dir=audit_dir)
    assert scaling["recommendation"] == "FIX_PAPER_PNL_SCALING"
    assert scaling["whether_new_clearance_allowed"] is False
    audit_dir.joinpath("paper_pnl_audit_summary.json").write_text(json.dumps({"paper_pnl_audit_status": "VALID_MICRO_DRAWDOWN_HALT", "root_cause": "DRAWDOWN_TRIGGER_VALID"}), encoding="utf-8")
    valid = run_paper_risk_recommendation(reports_root=tmp_path / "reports", pnl_audit_dir=audit_dir, output_dir=audit_dir)
    assert valid["recommendation"] == "REDUCE_MICRO_RISK_FURTHER"
    assert valid["safe_to_clear_again"] is False


def test_cli_modes_generate_reports_and_never_attempt_execution(tmp_path: Path, capsys) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    reports, paper_risk, daily = _reports(tmp_path, limit=-3.0)
    config = _micro_ini(paper_risk / "balanced_stable_micro.ini", 0.1)
    try:
        db.insert_paper_trade(_trade("cli_valid", profit=-10.0, metadata={"profile": "BALANCED_STABLE_MICRO", "paper_risk_multiplier": 0.1}))
        _halt(db)
    finally:
        db.close()
    assert (
        cli.main(
            [
                "--mode",
                "paper-pnl-audit",
                "--sqlite",
                str(tmp_path / "paper.sqlite3"),
                "--reports-root",
                str(reports),
                "--paper-risk-dir",
                str(paper_risk),
                "--daily-risk-dir",
                str(daily),
                "--profile-config",
                str(config),
                "--output-dir",
                str(tmp_path / "audit"),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert '"execution_attempted": false' in out
    assert '"order_send_called": false' in out
    assert (tmp_path / "audit" / "paper_pnl_audit_summary.json").exists()
    assert cli.main(["--mode", "paper-risk-recommendation", "--reports-root", str(reports), "--pnl-audit-dir", str(tmp_path / "audit"), "--output-dir", str(tmp_path / "audit")]) == 0
    rec = json.loads((tmp_path / "audit" / "paper_risk_recommendation.json").read_text(encoding="utf-8"))
    assert rec["execution_attempted"] is False
    assert rec["order_check_called"] is False
