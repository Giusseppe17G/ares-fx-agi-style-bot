from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor import run_micro_v2_dry_run_monitor


def test_v2_active_no_data(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], _iso_now(), mt5_connected=True)

    summary = _run(paths)

    assert summary["micro_v2_dry_run_monitor_status"] == "MICRO_V2_DRY_RUN_ACTIVE_NO_DATA_YET"
    assert summary["recommended_next_action"] == "KEEP_COLLECTING_V2_DATA"
    assert summary["v2_signals_detected"] == 0
    assert summary["execution_attempted"] is False


def test_v2_with_insufficient_data_needs_more_time(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], _iso_now(), mt5_connected=True)
    _insert_event(paths["v2_sqlite"], "SIGNAL_DETECTED", _iso_now(), payload={"symbol": "EURUSD"})
    _insert_trade(paths["v2_sqlite"], "CLOSED", _iso_now(-2), _iso_now(-1), symbol="EURUSD")

    summary = _run(paths)

    assert summary["micro_v2_dry_run_monitor_status"] == "MICRO_V2_DRY_RUN_NEEDS_MORE_TIME"
    assert summary["v2_paper_trades_closed"] == 1
    assert summary["recommended_next_action"] == "KEEP_COLLECTING_V2_DATA"


def test_stale_heartbeat_not_running(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], _iso_now(-120), mt5_connected=True)

    summary = _run(paths)

    assert summary["micro_v2_dry_run_monitor_status"] == "MICRO_V2_DRY_RUN_NOT_RUNNING"


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], _iso_now(), mt5_connected=True)
    _insert_event(paths["v2_sqlite"], "SAFETY_TEST", _iso_now(), payload={"execution_attempted": True})

    summary = _run(paths)

    assert summary["micro_v2_dry_run_monitor_status"] == "MICRO_V2_DRY_RUN_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_comparison_does_not_modify_sqlite(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["base_sqlite"], _iso_now(-5), mt5_connected=True)
    _insert_heartbeat(paths["v2_sqlite"], _iso_now(), mt5_connected=True)
    _insert_trade(paths["base_sqlite"], "CLOSED", _iso_now(-48), _iso_now(-47), symbol="GBPUSD")
    base_before = paths["base_sqlite"].read_bytes()
    v2_before = paths["v2_sqlite"].read_bytes()

    summary = _run(paths)

    assert summary["base_closed_trade_rate_per_24h"] >= 0
    assert paths["base_sqlite"].read_bytes() == base_before
    assert paths["v2_sqlite"].read_bytes() == v2_before


def test_cli_mode_generates_reports(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"], _iso_now(), mt5_connected=True)

    result = cli.main(
        [
            "--mode",
            "micro-v2-dry-run-monitor",
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
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["mode"] == "micro-v2-dry-run-monitor"
    assert summary["micro_v2_dry_run_monitor_status"] == "MICRO_V2_DRY_RUN_ACTIVE_NO_DATA_YET"
    assert (paths["out"] / "micro_v2_dry_run_monitor_summary.json").exists()
    assert (paths["out"] / "base_vs_v2_metrics.csv").exists()
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_dry_run_monitor(
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "out": tmp_path / "data" / "reports" / "micro_v2_dry_run_monitor",
    }
    for key in ("base_log_dir", "v2_log_dir", "reports_root"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["base_sqlite"])
    _init_db(paths["v2_sqlite"])
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


def _insert_heartbeat(path: Path, timestamp: str, *, mt5_connected: bool) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", timestamp, "forward-shadow", int(mt5_connected), 0, json.dumps({"mt5_connected": mt5_connected, "execution_attempted": False})),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_event(path: Path, event_type: str, timestamp: str, *, payload: dict[str, object] | None = None) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, str((payload or {}).get("symbol", "")), timestamp, "INFO", event_type, json.dumps(payload or {})),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_trade(path: Path, status: str, opened: str, closed: str | None, *, symbol: str) -> None:
    conn = sqlite3.connect(path)
    try:
        payload = {"paper_trade_id": f"ptr_{symbol}", "symbol": symbol, "status": status, "scaled_paper_pnl": 0.5}
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, symbol, status, payload_json, opened_at_utc, closed_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (payload["paper_trade_id"], symbol, status, json.dumps(payload), opened, closed),
        )
        conn.commit()
    finally:
        conn.close()


def _iso_now(minutes_delta: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_delta)).isoformat()
