from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.forward_evidence import run_forward_acceptance, run_forward_evidence
from agi_style_forex_bot_mt5.forward_evidence.drift_summary import summarize_forward_drift
from agi_style_forex_bot_mt5.forward_evidence.paper_trade_audit import audit_paper_trades
from agi_style_forex_bot_mt5.observability import HeartbeatWriter
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_forward_evidence_generates_summary_with_empty_sqlite(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        reports = tmp_path / "reports"
        _stable_gate(reports)
        summary = run_forward_evidence(database=db, log_dir=tmp_path / "logs", reports_root=reports, output_dir=tmp_path / "evidence")

        assert summary["mode"] == "forward-evidence"
        assert summary["heartbeat_count"] == 0
        assert (tmp_path / "evidence" / "evidence_summary.json").exists()
        assert summary["execution_attempted"] is False
    finally:
        db.close()


def test_forward_evidence_detects_heartbeat(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        HeartbeatWriter(db).write({"mode": "forward-shadow", "mt5_connected": True, "symbols_seen": 3, "execution_attempted": False})
        reports = tmp_path / "reports"
        _stable_gate(reports)
        summary = run_forward_evidence(database=db, log_dir=tmp_path / "logs", reports_root=reports, output_dir=tmp_path / "evidence")

        assert summary["heartbeat_count"] == 1
        assert summary["mt5_connected_count"] == 1
    finally:
        db.close()


def test_paper_trade_audit_detects_missing_sl_tp(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        trade = _trade("ptr_bad", sl_price=0.0, tp_price=0.0)
        db.insert_paper_trade(trade)
        audit = audit_paper_trades(database=db)

        assert audit["status"] == "FAILED"
        assert any(item["issue"] == "MISSING_SL_TP" for item in audit["issues"])
    finally:
        db.close()


def test_acceptance_needs_more_data_with_few_trades(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        HeartbeatWriter(db).write({"mode": "forward-shadow", "mt5_connected": True, "execution_attempted": False})
        reports = tmp_path / "reports"
        _stable_gate(reports)
        summary = run_forward_acceptance(database=db, log_dir=tmp_path / "logs", reports_root=reports, output_dir=tmp_path / "evidence")

        assert summary["decision"] == "NEEDS_MORE_FORWARD_DATA"
        assert summary["execution_attempted"] is False
    finally:
        db.close()


def test_acceptance_pauses_if_execution_attempted_true(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    try:
        HeartbeatWriter(db).write({"mode": "forward-shadow", "mt5_connected": True, "execution_attempted": False})
        db.insert_event(
            {
                "event_id": "evt_exec",
                "idempotency_key": "evt_exec",
                "run_id": "test",
                "environment": "DEMO",
                "severity": "CRITICAL",
                "module": "test",
                "event_type": "EXECUTION_ATTEMPTED",
                "message": "execution attempted",
                "payload": {"execution_attempted": True},
            }
        )
        reports = tmp_path / "reports"
        _stable_gate(reports)
        summary = run_forward_acceptance(database=db, log_dir=tmp_path / "logs", reports_root=reports, output_dir=tmp_path / "evidence")

        assert summary["decision"] == "PAUSE_FORWARD_SHADOW"
    finally:
        db.close()


def test_drift_summary_detects_critical_drift() -> None:
    drift = summarize_forward_drift(
        forward_metrics={"closed_trades": 20, "forward_winrate": 10, "forward_profit_factor": 0.5, "forward_expectancy_r": -0.2, "signal_frequency_per_day": 0},
        baseline={"winrate": 45, "profit_factor": 1.6, "expectancy_r": 0.3},
    )

    assert drift["classification"] == "CRITICAL_DRIFT"
    assert drift["execution_attempted"] is False


def test_cli_forward_evidence_and_acceptance_generate_reports(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "forward.sqlite3"
    db = TelemetryDatabase(sqlite)
    try:
        HeartbeatWriter(db).write({"mode": "forward-shadow", "mt5_connected": True, "execution_attempted": False})
    finally:
        db.close()
    reports = tmp_path / "reports"
    _stable_gate(reports)

    assert cli.main(["--mode", "forward-evidence", "--sqlite", str(sqlite), "--log-dir", str(tmp_path / "logs"), "--reports-root", str(reports), "--output-dir", str(tmp_path / "evidence")]) == 0
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["execution_attempted"] is False
    assert (tmp_path / "evidence" / "evidence_summary.json").exists()

    assert cli.main(["--mode", "forward-acceptance", "--sqlite", str(sqlite), "--log-dir", str(tmp_path / "logs"), "--reports-root", str(reports), "--output-dir", str(tmp_path / "evidence")]) == 0
    acceptance = json.loads(capsys.readouterr().out)
    assert acceptance["execution_attempted"] is False
    assert (tmp_path / "evidence" / "operational_acceptance.json").exists()


def _stable_gate(root: Path) -> None:
    path = root / "stable_gate"
    path.mkdir(parents=True)
    (path / "stable_gate_summary.json").write_text(
        json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True, "winrate": 42, "profit_factor": 1.6, "expectancy_r": 0.3, "execution_attempted": False}),
        encoding="utf-8",
    )


def _trade(trade_id: str, *, sl_price: float = 1.09, tp_price: float = 1.12) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig_{trade_id}",
        "idempotency_key": f"idem_{trade_id}",
        "symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "direction": "BUY",
        "entry_time_utc": now.isoformat(),
        "exit_time_utc": (now + timedelta(hours=1)).isoformat(),
        "entry_price": 1.1,
        "exit_price": 1.11,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "lot": 0.01,
        "risk_pct": 0.5,
        "risk_amount": 50,
        "strategy_name": "trend_pullback",
        "strategy_version": "0.1.0",
        "regime": "TREND_UP",
        "session": "LONDON",
        "score": 70,
        "reasons": ["test"],
        "status": "CLOSED",
        "profit": 50,
        "r_multiple": 0.5,
        "metadata": {"profile": "BALANCED_STABLE", "stable_profile_hash": "abc"},
    }
