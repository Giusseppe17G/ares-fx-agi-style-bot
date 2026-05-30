from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_frequency_calibration import run_micro_frequency_calibration
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_cli_mode_exists_and_generates_reports(tmp_path: Path, capsys) -> None:
    sqlite = tmp_path / "paper.sqlite3"
    profile = _profile(tmp_path)
    db = TelemetryDatabase(sqlite)
    try:
        _insert_event(db, "SIGNAL_REJECTED", "EURUSD", "2026-05-28T00:00:00+00:00", {"reject_reason": "ENSEMBLE_SCORE_LOW"})
    finally:
        db.close()

    assert cli.main(["--mode", "micro-frequency-calibration", "--sqlite", str(sqlite), "--reports-root", str(tmp_path / "reports"), "--profile-config", str(profile), "--output-dir", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["mode"] == "micro-frequency-calibration"
    assert (tmp_path / "out" / "micro_frequency_summary.json").exists()
    assert summary["execution_attempted"] is False


def test_low_trade_frequency_confirmed_after_48h_with_less_than_10_closed(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile = _profile(tmp_path)
    try:
        db.insert_heartbeat({"heartbeat_id": "hb1", "timestamp_utc": "2026-05-26T00:00:00+00:00", "mode": "forward-shadow", "mt5_connected": True})
        db.insert_heartbeat({"heartbeat_id": "hb2", "timestamp_utc": "2026-05-28T03:00:00+00:00", "mode": "forward-shadow", "mt5_connected": True})
        for idx in range(8):
            db.insert_paper_trade(_trade(f"ptr{idx}", "EURUSD", opened="2026-05-28T00:00:00+00:00", closed="2026-05-28T01:00:00+00:00"))
        summary = run_micro_frequency_calibration(database=db, reports_root=tmp_path / "reports", profile_config=profile, output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["hours_observed"] > 48
    assert summary["paper_trades_closed"] == 8
    assert summary["micro_frequency_status"] == "LOW_TRADE_FREQUENCY_CONFIRMED"


def test_filters_too_restrictive_with_high_rejection_rate(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile = _profile(tmp_path)
    try:
        for idx in range(5):
            _insert_event(db, "SIGNAL_REJECTED", "GBPUSD", f"2026-05-28T00:0{idx}:00+00:00", {"reject_reason": "REGIME_MISMATCH"})
        summary = run_micro_frequency_calibration(database=db, reports_root=tmp_path / "reports", profile_config=profile, output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["rejection_rate"] == 1.0
    assert summary["micro_frequency_status"] == "FILTERS_TOO_RESTRICTIVE"


def test_generates_candidate_ini_as_research_only(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile = _profile(tmp_path)
    try:
        summary = run_micro_frequency_calibration(database=db, reports_root=tmp_path / "reports", profile_config=profile, output_dir=tmp_path / "out")
    finally:
        db.close()

    candidate = tmp_path / "out" / "balanced_stable_micro_v2_candidate.ini"
    assert candidate.exists()
    text = candidate.read_text(encoding="utf-8")
    assert "NOT_ACTIVE_RESEARCH_ONLY=true" in text
    assert "NOT_FOR_DEMO_LIVE=true" in text
    assert "PAPER_ONLY=true" in text
    assert summary["candidate_profile_available"] is True


def test_does_not_modify_balanced_stable_micro_ini(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile = _profile(tmp_path)
    before = profile.read_text(encoding="utf-8")
    try:
        run_micro_frequency_calibration(database=db, reports_root=tmp_path / "reports", profile_config=profile, output_dir=tmp_path / "out")
    finally:
        db.close()

    assert profile.read_text(encoding="utf-8") == before


def test_does_not_modify_sqlite(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile = _profile(tmp_path)
    try:
        _insert_event(db, "SIGNAL_REJECTED", "USDJPY", "2026-05-28T00:00:00+00:00", {"reject_reason": "PAPER_COOLDOWN_BLOCK"})
        before = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
        summary = run_micro_frequency_calibration(database=db, reports_root=tmp_path / "reports", profile_config=profile, output_dir=tmp_path / "out")
        after = (db.count_rows("events"), db.count_rows("paper_trades"), db.get_operational_state())
    finally:
        db.close()

    assert before == after
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False
    assert summary["execution_attempted"] is False


def test_no_failure_with_minimal_data(tmp_path: Path) -> None:
    db = TelemetryDatabase(tmp_path / "paper.sqlite3")
    profile = _profile(tmp_path)
    try:
        summary = run_micro_frequency_calibration(database=db, reports_root=tmp_path / "reports", profile_config=profile, output_dir=tmp_path / "out")
    finally:
        db.close()

    assert summary["micro_frequency_status"] in {"DO_NOT_RELAX_PROFILE", "LOW_TRADE_FREQUENCY_CONFIRMED", "FREQUENCY_ACCEPTABLE_WAIT"}
    assert summary["execution_attempted"] is False


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


def _trade(trade_id: str, symbol: str, *, opened: str, closed: str) -> dict[str, object]:
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
        "status": "CLOSED",
        "scaled_paper_pnl": 0.1,
    }


def _profile(tmp_path: Path) -> Path:
    path = tmp_path / "balanced_stable_micro.ini"
    path.write_text(
        "\n".join(
            [
                "SIGNAL_PROFILE=BALANCED_STABLE_MICRO",
                "BASE_PROFILE=BALANCED_STABLE",
                "NOT_FOR_DEMO_LIVE=true",
                "PAPER_ONLY=true",
                "PAPER_RISK_MULTIPLIER=0.1",
                "MAX_OPEN_PAPER_TRADES=1",
                "MAX_PAPER_TRADES_PER_DAY=2",
                "COOLDOWN_AFTER_LOSS_MINUTES=120",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path
