from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_checkpoint_runner import run_micro_v2_observation_checkpoint


def test_market_closed_dominates_waiting_for_market_open(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"])
    _event(paths["v2_sqlite"], "MARKET_CLOSED_REJECTION", "EURUSD", {"market_is_probably_closed": True})

    summary = _run(paths)

    assert summary["micro_v2_checkpoint_status"] == "MICRO_V2_CHECKPOINT_WAITING_FOR_MARKET_OPEN"
    assert summary["market_closed_rejection_count"] == 1


def test_fresh_ticks_without_trades_collecting_data(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"])
    _event(paths["v2_sqlite"], "SYMBOL_ACCEPTED", "EURUSD", {"tick_time_status": "FRESH", "tick_age_seconds": 1})

    summary = _run(paths)

    assert summary["micro_v2_checkpoint_status"] == "MICRO_V2_CHECKPOINT_COLLECTING_FRESH_TICK_DATA"
    assert summary["fresh_tick_symbols"] == ["EURUSD"]


def test_high_rejection_with_fresh_ticks_ready_for_filter_analysis(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"])
    _event(paths["v2_sqlite"], "SYMBOL_ACCEPTED", "EURUSD", {"tick_time_status": "FRESH", "tick_age_seconds": 1})
    for _ in range(5):
        _event(paths["v2_sqlite"], "STALE_TICK_REJECTION", "EURUSD", {"reason": "STALE_TICK_REJECTION"})

    summary = _run(paths)

    assert summary["micro_v2_checkpoint_status"] == "MICRO_V2_CHECKPOINT_READY_FOR_FILTER_ANALYSIS"
    assert summary["v2_rejection_rate"] >= 0.8


def test_closed_trades_under_required_needs_more_trades(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"])
    for idx in range(3):
        _trade(paths["v2_sqlite"], f"ptr{idx}", "CLOSED", closed_hours_ago=idx)

    summary = _run(paths)

    assert summary["micro_v2_checkpoint_status"] == "MICRO_V2_CHECKPOINT_NEEDS_MORE_TRADES"
    assert summary["v2_paper_trades_closed"] == 3


def test_ten_closed_trades_and_24h_ready_for_acceptance_review(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"])
    for idx in range(10):
        _trade(paths["v2_sqlite"], f"ptr{idx}", "CLOSED", opened_hours_ago=30 - idx, closed_hours_ago=20 - idx)

    summary = _run(paths)

    assert summary["micro_v2_checkpoint_status"] == "MICRO_V2_CHECKPOINT_READY_FOR_ACCEPTANCE_REVIEW"
    assert summary["v2_paper_trades_closed"] == 10


def test_stale_heartbeat_runtime_not_running(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"], minutes_delta=-60)
    _event(paths["v2_sqlite"], "MARKET_CLOSED_REJECTION", "EURUSD", {"market_is_probably_closed": True})

    summary = _run(paths)

    assert summary["micro_v2_checkpoint_status"] == "MICRO_V2_CHECKPOINT_RUNTIME_NOT_RUNNING"


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"])
    _event(paths["v2_sqlite"], "SYMBOL_ACCEPTED", "EURUSD", {"execution_attempted": True})

    summary = _run(paths)

    assert summary["micro_v2_checkpoint_status"] == "MICRO_V2_CHECKPOINT_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_cli_does_not_modify_sqlite_or_logs(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"])
    _event(paths["v2_sqlite"], "MARKET_CLOSED_REJECTION", "EURUSD", {"market_is_probably_closed": True})
    log_path = paths["v2_log_dir"] / "events.jsonl"
    sqlite_before = paths["v2_sqlite"].read_bytes()
    log_before = log_path.read_text(encoding="utf-8")

    result = cli.main(
        [
            "--mode",
            "micro-v2-observation-checkpoint",
            "--base-sqlite",
            str(paths["base_sqlite"]),
            "--base-log-dir",
            str(paths["base_log_dir"]),
            "--v2-sqlite",
            str(paths["v2_sqlite"]),
            "--v2-log-dir",
            str(paths["v2_log_dir"]),
            "--reports-root",
            str(paths["reports_root"]),
            "--v2-profile-config",
            str(paths["profile"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["micro_v2_checkpoint_status"] == "MICRO_V2_CHECKPOINT_WAITING_FOR_MARKET_OPEN"
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert log_path.read_text(encoding="utf-8") == log_before


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_observation_checkpoint(
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "out": tmp_path / "data" / "reports" / "micro_v2_observation_checkpoint",
    }
    for key in ("base_log_dir", "v2_log_dir", "reports_root"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["base_sqlite"])
    _init_db(paths["v2_sqlite"])
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    (paths["base_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    paths["profile"].parent.mkdir(parents=True, exist_ok=True)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    return paths


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)")
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT)")
        conn.commit()
    finally:
        conn.close()


def _heartbeat(path: Path, *, minutes_delta: int = 0, hours_ago: int | None = None) -> None:
    timestamp = datetime.now(timezone.utc) + timedelta(minutes=minutes_delta)
    if hours_ago is not None:
        timestamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", timestamp.isoformat(), "forward-shadow", 1, 0, json.dumps({"mt5_connected": True, "execution_attempted": False})),
        )
        conn.commit()
    finally:
        conn.close()


def _event(path: Path, event_type: str, symbol: str, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, symbol, datetime.now(timezone.utc).isoformat(), "INFO", event_type, json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _trade(path: Path, trade_id: str, status: str, *, opened_hours_ago: int = 1, closed_hours_ago: int = 0) -> None:
    opened = datetime.now(timezone.utc) - timedelta(hours=opened_hours_ago)
    closed = datetime.now(timezone.utc) - timedelta(hours=closed_hours_ago)
    payload = {"paper_trade_id": trade_id, "symbol": "EURUSD", "status": status, "scaled_paper_pnl": 0.1}
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, symbol, status, payload_json, opened_at_utc, closed_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (trade_id, "EURUSD", status, json.dumps(payload), opened.isoformat(), closed.isoformat() if status == "CLOSED" else ""),
        )
        conn.commit()
    finally:
        conn.close()
