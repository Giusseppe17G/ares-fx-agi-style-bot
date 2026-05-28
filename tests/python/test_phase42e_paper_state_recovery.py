from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.forward_evidence.operational_acceptance_gate import decide_operational_acceptance
from agi_style_forex_bot_mt5.paper_trading.paper_state_recovery import close_stale_open_paper_trade, run_paper_state_recovery_audit
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_config_error_missing_profile_config_detected(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        db.update_operational_state({"latest_exit_reason": "CONFIG_ERROR", "halt_reason": "PAPER_STATE_ERROR"})
        summary = run_paper_state_recovery_audit(
            database=db,
            profile_config=tmp_path / "missing.ini",
            stable_gate=_stable_gate(tmp_path),
            clearance_ledger=_file(tmp_path / "clearance.json", {}),
            daily_risk_ledger=_file(tmp_path / "daily.json", {}),
            output_dir=tmp_path / "out",
        )
    finally:
        db.close()

    assert summary["config_error_detected"] is True
    assert summary["config_error_root_cause"] == "missing_profile_config"
    assert summary["config_error_blocking"] is True
    assert summary["execution_attempted"] is False


def test_open_paper_trade_valid_not_closed_automatically(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        db.insert_paper_trade(_trade("t1", datetime.now(timezone.utc).isoformat()))
        summary = run_paper_state_recovery_audit(database=db, profile_config=_profile(tmp_path), stable_gate=_stable_gate(tmp_path), clearance_ledger=_file(tmp_path / "clearance.json", {}), daily_risk_ledger=_file(tmp_path / "daily.json", {}), output_dir=tmp_path / "out")
        rows = db.fetch_open_paper_trades()
    finally:
        db.close()

    assert summary["valid_open_trade_count"] == 1
    assert summary["requires_paper_only_close"] is False
    assert len(rows) == 1


def test_open_paper_trade_stale_requires_paper_only_close(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    try:
        db.insert_paper_trade(_trade("t1", old))
        summary = run_paper_state_recovery_audit(database=db, profile_config=_profile(tmp_path), stable_gate=_stable_gate(tmp_path), clearance_ledger=_file(tmp_path / "clearance.json", {}), daily_risk_ledger=_file(tmp_path / "daily.json", {}), output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["stale_open_trade_count"] == 1
    assert summary["requires_paper_only_close"] is True


def test_paper_close_stale_open_trade_requires_confirm(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    try:
        db.insert_paper_trade(_trade("t1", old))
        dry = close_stale_open_paper_trade(database=db, reason="reviewed", output_dir=tmp_path / "out", confirm_paper_only=False)
        assert len(db.fetch_open_paper_trades()) == 1
        closed = close_stale_open_paper_trade(database=db, reason="reviewed", output_dir=tmp_path / "out", confirm_paper_only=True)
        assert len(db.fetch_open_paper_trades()) == 0
    finally:
        db.close()

    assert dry["dry_run"] is True
    assert dry["paper_trades_closed"] == 0
    assert closed["paper_close_status"] == "PAPER_CLOSE_STALE_COMPLETED"
    assert closed["order_send_called"] is False


def test_forward_acceptance_blocks_paper_state_error() -> None:
    decision = decide_operational_acceptance(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "hours_observed": 1},
        metrics={"paper_drawdown_status": "OK", "closed_trades": 0},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_CLEAN", "telemetry_acceptance_clear": True},
        paper_state_recovery={"recovery_required": True, "paper_state_clean_for_observation": False, "recovery_recommended_action": "FIX_CONFIG_AND_RERUN", "paper_state_recovery_status": "PAPER_STATE_RECOVERY_CONFIG_BLOCKED", "config_error_root_cause": "missing_profile_config"},
    )

    assert decision["decision"] == "PAUSE_FORWARD_SHADOW"
    assert decision["config_error_root_cause"] == "missing_profile_config"
    assert decision["execution_attempted"] is False


def test_forward_acceptance_allows_valid_open_trade_needs_more_data() -> None:
    decision = decide_operational_acceptance(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "hours_observed": 1, "open_paper_trades": 1},
        metrics={"paper_drawdown_status": "OK", "closed_trades": 0},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_CLEAN", "telemetry_acceptance_clear": True},
        paper_state_recovery={"recovery_required": False, "can_safely_continue_with_open_trade": True, "paper_state_clean_for_observation": True, "valid_open_trade_count": 1},
    )

    assert decision["decision"] == "NEEDS_MORE_FORWARD_DATA"
    assert decision["order_check_called"] is False


def test_cli_recovery_modes(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "paper.sqlite3"
    db = TelemetryDatabase(sqlite)
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    try:
        db.insert_paper_trade(_trade("t1", old))
    finally:
        db.close()
    profile = _profile(tmp_path)
    stable = _stable_gate(tmp_path)
    clearance = _file(tmp_path / "clearance.json", {})
    daily = _file(tmp_path / "daily.json", {})

    assert cli.main(["--mode", "paper-state-recovery-audit", "--sqlite", str(sqlite), "--profile-config", str(profile), "--stable-gate", str(stable), "--clearance-ledger", str(clearance), "--daily-risk-ledger", str(daily), "--output-dir", str(tmp_path / "out")]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["stale_open_trade_count"] == 1
    assert cli.main(["--mode", "paper-state-recovery-plan", "--output-dir", str(tmp_path / "out")]) == 0
    capsys.readouterr()
    assert (tmp_path / "out" / "PAPER_STATE_RECOVERY_PLAN.md").exists()
    assert cli.main(["--mode", "paper-close-stale-open-trade", "--sqlite", str(sqlite), "--reason", "reviewed", "--output-dir", str(tmp_path / "out")]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["dry_run"] is True


def _trade(trade_id: str, opened: str) -> dict[str, object]:
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig-{trade_id}",
        "idempotency_key": f"idem-{trade_id}",
        "symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "direction": "BUY",
        "entry_time_utc": opened,
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
        "lot": 0.01,
        "risk_pct": 0.1,
        "risk_amount": 1.0,
        "strategy_name": "test_strategy",
        "strategy_version": "1",
        "regime": "RANGE",
        "session": "LONDON",
        "score": 70,
        "reasons": [],
        "status": "OPEN",
        "scaled_paper_pnl": 0.0,
        "pnl_scaling_status": "SCALED_PAPER_PNL",
    }


def _profile(tmp_path: Path) -> Path:
    return _file(tmp_path / "balanced_stable_micro.ini", "profile=BALANCED_STABLE_MICRO\nPAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\n")


def _stable_gate(tmp_path: Path) -> Path:
    return _file(tmp_path / "stable_gate.json", {"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True})


def _file(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path
