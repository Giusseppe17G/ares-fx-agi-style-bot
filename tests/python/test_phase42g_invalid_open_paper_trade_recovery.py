from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.forward_evidence.operational_acceptance_gate import decide_operational_acceptance
from agi_style_forex_bot_mt5.paper_trading.config_error_root_cause import run_config_error_root_cause_audit
from agi_style_forex_bot_mt5.paper_trading.paper_state_recovery import close_invalid_open_paper_trade, run_invalid_open_paper_trade_audit, run_paper_state_recovery_audit
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_detects_zero_risk_open_trade(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        db.insert_paper_trade(_trade("ptr1", entry=1.16111, sl=1.16111))
        summary = run_invalid_open_paper_trade_audit(database=db, output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["invalid_open_trade_count"] == 1
    assert summary["zero_risk_distance_count"] == 1
    assert summary["invalid_open_trade_status"] == "ZERO_RISK_OPEN_PAPER_TRADE_FOUND"
    assert summary["execution_attempted"] is False


def test_close_invalid_requires_confirm(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        db.insert_paper_trade(_trade("ptr1", entry=1.16111, sl=1.16111))
        summary = close_invalid_open_paper_trade(database=db, trade_id="ptr1", reason="reviewed", output_dir=tmp_path / "out", confirm_paper_only=False)
        assert len(db.fetch_open_paper_trades()) == 1
    finally:
        db.close()

    assert summary["paper_close_invalid_status"] == "PAPER_CLOSE_INVALID_DRY_RUN"
    assert summary["paper_trades_closed"] == 0


def test_does_not_close_valid_trade(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        db.insert_paper_trade(_trade("ptr1", entry=1.16111, sl=1.16011))
        summary = close_invalid_open_paper_trade(database=db, trade_id="ptr1", reason="reviewed", output_dir=tmp_path / "out", confirm_paper_only=True)
        assert len(db.fetch_open_paper_trades()) == 1
    finally:
        db.close()

    assert summary["paper_close_invalid_status"] == "PAPER_CLOSE_INVALID_DENIED_TRADE_VALID"
    assert summary["order_send_called"] is False


def test_closes_invalid_trade_paper_only_and_writes_ledger(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        db.insert_paper_trade(_trade("ptr1", entry=1.16111, sl=1.16111))
        summary = close_invalid_open_paper_trade(database=db, trade_id="ptr1", reason="Close zero risk paper trade", output_dir=tmp_path / "out", confirm_paper_only=True)
        open_rows = db.fetch_open_paper_trades()
        state = db.get_operational_state()
    finally:
        db.close()

    assert summary["paper_close_invalid_status"] == "PAPER_CLOSE_INVALID_COMPLETED"
    assert summary["paper_trades_closed"] == 1
    assert len(open_rows) == 0
    assert state["invalid_open_paper_trade_resolved"] is True
    assert (tmp_path / "out" / "invalid_trade_close_ledger.json").exists()
    assert summary["execution_attempted"] is False


def test_recovery_clear_after_invalid_close(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        db.insert_paper_trade(_trade("ptr1", entry=1.16111, sl=1.16111))
        close_invalid_open_paper_trade(database=db, trade_id="ptr1", reason="reviewed", output_dir=tmp_path / "out", confirm_paper_only=True)
        recovery = run_paper_state_recovery_audit(database=db, profile_config=_profile(tmp_path), stable_gate=_stable_gate(tmp_path), clearance_ledger=_file(tmp_path / "clearance.json", {}), daily_risk_ledger=_file(tmp_path / "daily.json", {}), output_dir=tmp_path / "recovery")
    finally:
        db.close()

    assert recovery["open_paper_trades_count"] == 0
    assert recovery["invalid_risk_open_trade_count"] == 0
    assert recovery["paper_state_recovery_status"] == "PAPER_STATE_RECOVERY_OK"
    assert recovery["config_error_resolved"] is True
    assert recovery["can_rerun_forward_shadow_after_fix"] is True


def test_config_root_cause_resolved_after_invalid_close(tmp_path: Path) -> None:
    db = _db(tmp_path)
    try:
        db.insert_paper_trade(_trade("ptr1", entry=1.16111, sl=1.16111))
        close_invalid_open_paper_trade(database=db, trade_id="ptr1", reason="reviewed", output_dir=tmp_path / "out", confirm_paper_only=True)
        root = run_config_error_root_cause_audit(database=db, log_dir=tmp_path / "logs", profile_config=_profile(tmp_path), stable_gate=_stable_gate(tmp_path), clearance_ledger=_file(tmp_path / "clearance.json", {"clearances": [{"cleared_for_profile": "BALANCED_STABLE_MICRO", "cleared_for_paper_shadow": True}]}), daily_risk_ledger=_file(tmp_path / "daily.json", {"daily_risk_clearances": [{"cleared_for_profile": "BALANCED_STABLE_MICRO", "cleared_for_paper_shadow": True}]}), output_dir=tmp_path / "root")
    finally:
        db.close()

    assert root["config_error_detected"] is False
    assert root["config_error_root_cause"] == "RESOLVED_INVALID_OPEN_PAPER_TRADE"
    assert root["can_rerun_forward_shadow_after_fix"] is True


def test_forward_acceptance_needs_more_data_after_recovery_clear() -> None:
    decision = decide_operational_acceptance(
        evidence={"execution_attempted": False, "order_send_called": False, "order_check_called": False, "stable_gate_confirmed": True, "heartbeat_count": 1, "hours_observed": 1},
        metrics={"paper_drawdown_status": "OK", "closed_trades": 0},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_CLEAR"},
        telemetry_summary={"telemetry_status": "TELEMETRY_CLEAN", "telemetry_acceptance_clear": True},
        paper_state_recovery={"recovery_required": False, "paper_state_clean_for_observation": True, "config_error_resolved": True, "open_paper_trades_count": 0},
    )

    assert decision["decision"] == "NEEDS_MORE_FORWARD_DATA"
    assert decision["order_check_called"] is False


def test_cli_invalid_trade_modes(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "paper.sqlite3"
    db = _db(tmp_path, sqlite=sqlite)
    try:
        db.insert_paper_trade(_trade("ptr1", entry=1.16111, sl=1.16111))
    finally:
        db.close()
    assert cli.main(["--mode", "invalid-open-paper-trade-audit", "--sqlite", str(sqlite), "--output-dir", str(tmp_path / "out")]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["invalid_open_trade_count"] == 1
    assert cli.main(["--mode", "paper-close-invalid-open-trade", "--sqlite", str(sqlite), "--trade-id", "ptr1", "--confirm-paper-only", "true", "--reason", "reviewed", "--output-dir", str(tmp_path / "out")]) == 0
    closed = json.loads(capsys.readouterr().out)
    assert closed["paper_trades_closed"] == 1


def _db(tmp_path: Path, sqlite: Path | None = None) -> TelemetryDatabase:
    db = TelemetryDatabase(sqlite or tmp_path / "paper.sqlite3")
    db.update_operational_state({"latest_exit_reason": "CONFIG_ERROR", "halt_reason": "PAPER_STATE_ERROR", "latest_forward_shadow_error": "paper trade has invalid risk distance"})
    return db


def _trade(trade_id: str, *, entry: float, sl: float) -> dict[str, object]:
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig-{trade_id}",
        "idempotency_key": f"idem-{trade_id}",
        "symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "direction": "BUY",
        "entry_time_utc": datetime.now(timezone.utc).isoformat(),
        "entry_price": entry,
        "sl_price": sl,
        "tp_price": 1.15932,
        "lot": 0.01,
        "risk_pct": 0.1,
        "risk_amount": 1.0,
        "strategy_name": "strategy_ensemble",
        "strategy_version": "1",
        "regime": "RANGE",
        "session": "LONDON",
        "score": 70,
        "reasons": [],
        "status": "OPEN",
        "scaled_paper_pnl": 0.0,
    }


def _profile(tmp_path: Path) -> Path:
    return _file(tmp_path / "balanced_stable_micro.ini", "SIGNAL_PROFILE=BALANCED_STABLE_MICRO\nPAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\nPAPER_RISK_MULTIPLIER=0.1\n")


def _stable_gate(tmp_path: Path) -> Path:
    return _file(tmp_path / "stable_gate.json", {"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True})


def _file(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path
