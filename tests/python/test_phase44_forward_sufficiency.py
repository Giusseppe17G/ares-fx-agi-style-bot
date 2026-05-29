from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.forward_sufficiency import run_forward_sufficiency_audit
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_cli_mode_exists_and_generates_reports(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "paper.sqlite3"
    db = TelemetryDatabase(sqlite)
    try:
        _insert_event(db, "SIGNAL_REJECTED", "EURUSD", "2026-05-28T00:00:00+00:00", {"reject_reason": "ENSEMBLE_SCORE_LOW"})
    finally:
        db.close()

    assert cli.main(["--mode", "forward-sufficiency-audit", "--sqlite", str(sqlite), "--reports-root", str(tmp_path / "reports"), "--output-dir", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["mode"] == "forward-sufficiency-audit"
    assert (tmp_path / "out" / "forward_sufficiency_summary.json").exists()
    assert summary["execution_attempted"] is False


def test_calculates_hours_observed(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        db.insert_heartbeat({"heartbeat_id": "hb1", "timestamp_utc": "2026-05-28T00:00:00+00:00", "mode": "forward-shadow", "mt5_connected": True})
        db.insert_heartbeat({"heartbeat_id": "hb2", "timestamp_utc": "2026-05-28T06:00:00+00:00", "mode": "forward-shadow", "mt5_connected": True})
        summary = run_forward_sufficiency_audit(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["hours_observed"] == 6.0


def test_needs_more_time_only(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        for idx in range(10):
            db.insert_paper_trade(_trade(f"ptr{idx}", "EURUSD", status="CLOSED", opened="2026-05-28T00:00:00+00:00", closed="2026-05-28T05:00:00+00:00"))
        summary = run_forward_sufficiency_audit(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["closed_paper_trades"] == 10
    assert summary["forward_sufficiency_status"] == "NEEDS_MORE_TIME_ONLY"


def test_needs_more_trades_only(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        db.insert_paper_trade(_trade("ptr1", "EURUSD", status="CLOSED", opened="2026-05-27T00:00:00+00:00", closed="2026-05-28T01:00:00+00:00"))
        summary = run_forward_sufficiency_audit(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["hours_observed"] == 25.0
    assert summary["forward_sufficiency_status"] == "NEEDS_MORE_TRADES_ONLY"


def test_low_trade_frequency(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        db.insert_heartbeat({"heartbeat_id": "hb1", "timestamp_utc": "2026-05-28T00:00:00+00:00", "mode": "forward-shadow", "mt5_connected": True})
        db.insert_heartbeat({"heartbeat_id": "hb2", "timestamp_utc": "2026-05-28T05:00:00+00:00", "mode": "forward-shadow", "mt5_connected": True})
        summary = run_forward_sufficiency_audit(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["forward_sufficiency_status"] == "LOW_TRADE_FREQUENCY"


def test_filters_too_restrictive_with_high_rejection_rate(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        for idx in range(5):
            _insert_event(db, "SIGNAL_REJECTED", "GBPUSD", f"2026-05-28T00:0{idx}:00+00:00", {"reject_reason": "ENSEMBLE_SCORE_LOW"})
        summary = run_forward_sufficiency_audit(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["rejection_rate"] == 1.0
    assert summary["forward_sufficiency_status"] == "FILTERS_TOO_RESTRICTIVE"


def test_no_failure_without_enough_data(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        summary = run_forward_sufficiency_audit(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["forward_sufficiency_status"] == "INSUFFICIENT_FORWARD_DATA"
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_does_not_modify_sqlite(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    try:
        _insert_event(db, "SIGNAL_REJECTED", "USDJPY", "2026-05-28T00:00:00+00:00", {"reject_reason": "SPREAD_BLOCK"})
        before = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
        summary = run_forward_sufficiency_audit(database=db, reports_root=tmp_path / "reports", output_dir=tmp_path / "out")
        after = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
    finally:
        db.close()

    assert before == after
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def _insert_event(db: TelemetryDatabase, event_type: str, symbol: str, timestamp: str, payload: dict[str, object]) -> None:
    event_id = f"evt_{event_type}_{symbol}_{db.count_rows('events')}"
    db.insert_event(
        {
            "event_id": event_id,
            "idempotency_key": event_id,
            "timestamp_utc": timestamp,
            "event_type": event_type,
            "symbol": symbol,
            "severity": "INFO",
            "module": "test",
            "message": event_type.lower(),
            "payload": payload,
        }
    )


def _trade(trade_id: str, symbol: str, *, status: str, opened: str, closed: str | None) -> dict[str, object]:
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig-{trade_id}",
        "idempotency_key": f"idem-{trade_id}",
        "symbol": symbol,
        "broker_symbol": symbol,
        "direction": "BUY",
        "entry_time_utc": opened,
        "exit_time_utc": closed,
        "entry_price": 1.1,
        "sl_price": 1.09,
        "tp_price": 1.12,
        "lot": 0.01,
        "risk_pct": 0.1,
        "risk_amount": 1.0,
        "strategy_name": "strategy_ensemble",
        "strategy_version": "1",
        "regime": "RANGE",
        "session": "LONDON",
        "score": 70,
        "reasons": [],
        "status": status,
        "scaled_paper_pnl": 0.1,
    }
