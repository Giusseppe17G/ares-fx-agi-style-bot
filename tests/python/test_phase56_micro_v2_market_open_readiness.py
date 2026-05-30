from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_market_open_readiness import run_micro_v2_market_open_readiness


def test_market_closed_dominant_waits_for_market_open(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], connected=True)
    _insert_event(paths["v2_sqlite"], "MARKET_CLOSED_REJECTION", "EURUSD", {"market_is_probably_closed": True})

    summary = _run(paths)

    assert summary["micro_v2_market_open_readiness_status"] == "MICRO_V2_WAITING_FOR_MARKET_OPEN"
    assert summary["market_closed_rejection_count"] == 1
    assert summary["execution_attempted"] is False


def test_heartbeat_stale_runtime_not_running(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], connected=True, minutes_delta=-120)
    _insert_event(paths["v2_sqlite"], "MARKET_CLOSED_REJECTION", "EURUSD", {"market_is_probably_closed": True})

    summary = _run(paths)

    assert summary["micro_v2_market_open_readiness_status"] == "MICRO_V2_RUNTIME_NOT_RUNNING"


def test_mt5_disconnected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], connected=False)

    summary = _run(paths)

    assert summary["micro_v2_market_open_readiness_status"] == "MICRO_V2_MT5_DISCONNECTED"
    assert summary["mt5_connected"] is False


def test_fresh_ticks_ready(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], connected=True)
    _insert_event(paths["v2_sqlite"], "SYMBOL_ACCEPTED", "EURUSD", {"symbol": "EURUSD", "tick_time_status": "FRESH", "tick_age_seconds": 1})

    summary = _run(paths)

    assert summary["micro_v2_market_open_readiness_status"] == "MICRO_V2_MARKET_OPEN_TICKS_FRESH"
    assert summary["fresh_tick_symbols"] == ["EURUSD"]
    assert summary["recommended_next_action"] == "CONTINUE_V2_PAPER_OBSERVATION"


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], connected=True)
    _insert_event(paths["v2_sqlite"], "MARKET_CLOSED_REJECTION", "EURUSD", {"execution_attempted": True})

    summary = _run(paths)

    assert summary["micro_v2_market_open_readiness_status"] == "MICRO_V2_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_cli_does_not_modify_sqlite_or_logs(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], connected=True)
    _insert_event(paths["v2_sqlite"], "SYMBOL_ACCEPTED", "EURUSD", {"symbol": "EURUSD", "tick_time_status": "FRESH", "tick_age_seconds": 1})
    log_path = paths["v2_log_dir"] / "events.jsonl"
    log_path.write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    sqlite_before = paths["v2_sqlite"].read_bytes()
    log_before = log_path.read_text(encoding="utf-8")

    result = cli.main(
        [
            "--mode",
            "micro-v2-market-open-readiness",
            "--v2-sqlite",
            str(paths["v2_sqlite"]),
            "--v2-log-dir",
            str(paths["v2_log_dir"]),
            "--reports-root",
            str(paths["reports_root"]),
            "--v2-profile-config",
            str(paths["profile"]),
            "--rejection-labeling-dir",
            str(paths["rejection_labeling_dir"]),
            "--monitor-dir",
            str(paths["monitor_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["micro_v2_market_open_readiness_status"] == "MICRO_V2_MARKET_OPEN_TICKS_FRESH"
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert log_path.read_text(encoding="utf-8") == log_before


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_market_open_readiness(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        rejection_labeling_dir=paths["rejection_labeling_dir"],
        monitor_dir=paths["monitor_dir"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "rejection_labeling_dir": tmp_path / "data" / "reports" / "rejection_labeling_audit",
        "monitor_dir": tmp_path / "data" / "reports" / "micro_v2_dry_run_monitor",
        "out": tmp_path / "data" / "reports" / "micro_v2_market_open_readiness",
    }
    for key in ("v2_log_dir", "reports_root", "rejection_labeling_dir", "monitor_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    paths["profile"].parent.mkdir(parents=True, exist_ok=True)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    (paths["rejection_labeling_dir"] / "rejection_labeling_summary.json").write_text(json.dumps({}), encoding="utf-8")
    (paths["monitor_dir"] / "micro_v2_dry_run_monitor_summary.json").write_text(json.dumps({}), encoding="utf-8")
    return paths


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)"
        )
        conn.execute(
            "CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)"
        )
        conn.execute(
            "CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT)"
        )
        conn.commit()
    finally:
        conn.close()


def _insert_heartbeat(path: Path, *, connected: bool, minutes_delta: int = 0) -> None:
    conn = sqlite3.connect(path)
    try:
        timestamp = (datetime.now(timezone.utc) + timedelta(minutes=minutes_delta)).isoformat()
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", timestamp, "forward-shadow", int(connected), 0, json.dumps({"mt5_connected": connected, "execution_attempted": False})),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_event(path: Path, event_type: str, symbol: str, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, symbol, datetime.now(timezone.utc).isoformat(), "INFO", event_type.lower(), json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()
