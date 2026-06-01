from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_stable_market_window import run_micro_v2_stable_market_window


def test_market_closed_dominates_not_stable(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.75, fresh=["EURUSD", "GBPUSD", "USDJPY"])
    summary = _run(paths)
    assert summary["micro_v2_stable_market_window_status"] == "MICRO_V2_MARKET_WINDOW_NOT_STABLE"


def test_partial_fresh_tick_coverage(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, fresh=["EURUSD"])
    summary = _run(paths)
    assert summary["micro_v2_stable_market_window_status"] == "MICRO_V2_MARKET_WINDOW_PARTIALLY_STABLE"
    assert summary["fresh_tick_coverage_ratio"] == 0.3333


def test_stable_no_trades_yet(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, fresh=["EURUSD", "GBPUSD"])
    summary = _run(paths)
    assert summary["micro_v2_stable_market_window_status"] == "MICRO_V2_MARKET_WINDOW_STABLE_NO_TRADES_YET"


def test_stable_collecting_one_to_nine_trades(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, fresh=["EURUSD", "GBPUSD"], closed_trades=3)
    summary = _run(paths)
    assert summary["micro_v2_stable_market_window_status"] == "MICRO_V2_MARKET_WINDOW_STABLE_COLLECTING_TRADES"


def test_trades_positive_but_partial_coverage_ready_lifecycle(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, fresh=["EURUSD"], closed_trades=2)
    summary = _run(paths)
    assert summary["micro_v2_stable_market_window_status"] == "MICRO_V2_READY_FOR_TRADE_FREQUENCY_LIFECYCLE_AUDIT"


def test_ten_trades_and_24h_ready_acceptance_pack(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, fresh=["EURUSD", "GBPUSD", "USDJPY"], closed_trades=10, old_event_hours=25)
    summary = _run(paths)
    assert summary["micro_v2_stable_market_window_status"] == "MICRO_V2_READY_FOR_ACCEPTANCE_EVIDENCE_PACK"


def test_runtime_not_running(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, fresh=["EURUSD", "GBPUSD"], stale_heartbeat=True)
    summary = _run(paths)
    assert summary["micro_v2_stable_market_window_status"] == "MICRO_V2_RUNTIME_NOT_RUNNING"


def test_mt5_disconnected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, fresh=["EURUSD", "GBPUSD"], mt5_connected=False)
    summary = _run(paths)
    assert summary["micro_v2_stable_market_window_status"] == "MICRO_V2_MT5_DISCONNECTED"


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, fresh=["EURUSD", "GBPUSD"], safety=True)
    summary = _run(paths)
    assert summary["micro_v2_stable_market_window_status"] == "MICRO_V2_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False


def test_cli_does_not_modify_sqlite_logs_or_profile(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path, market_ratio=0.1, fresh=["EURUSD", "GBPUSD"])
    sqlite_before = paths["v2_sqlite"].read_bytes()
    log_before = (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8")
    profile_before = paths["profile"].read_text(encoding="utf-8")
    result = cli.main(
        [
            "--mode",
            "micro-v2-stable-market-window",
            "--v2-sqlite",
            str(paths["v2_sqlite"]),
            "--v2-log-dir",
            str(paths["v2_log_dir"]),
            "--base-sqlite",
            str(paths["base_sqlite"]),
            "--base-log-dir",
            str(paths["base_log_dir"]),
            "--reports-root",
            str(paths["reports_root"]),
            "--v2-profile-config",
            str(paths["profile"]),
            "--checkpoint-dir",
            str(paths["checkpoint_dir"]),
            "--readiness-dir",
            str(paths["readiness_dir"]),
            "--filter-analysis-dir",
            str(paths["filter_analysis_dir"]),
            "--consolidated-dir",
            str(paths["consolidated_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )
    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["execution_attempted"] is False
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8") == log_before
    assert paths["profile"].read_text(encoding="utf-8") == profile_before


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_stable_market_window(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        checkpoint_dir=paths["checkpoint_dir"],
        readiness_dir=paths["readiness_dir"],
        filter_analysis_dir=paths["filter_analysis_dir"],
        consolidated_dir=paths["consolidated_dir"],
        output_dir=paths["out"],
    )


def _fixture(
    tmp_path: Path,
    *,
    market_ratio: float,
    fresh: list[str],
    closed_trades: int = 0,
    old_event_hours: int = 0,
    stale_heartbeat: bool = False,
    mt5_connected: bool = True,
    safety: bool = False,
) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "checkpoint_dir": tmp_path / "data" / "reports" / "micro_v2_observation_checkpoint",
        "readiness_dir": tmp_path / "data" / "reports" / "micro_v2_market_open_readiness",
        "filter_analysis_dir": tmp_path / "data" / "reports" / "micro_v2_filter_analysis",
        "consolidated_dir": tmp_path / "data" / "reports" / "micro_v2_consolidated_audit",
        "out": tmp_path / "data" / "reports" / "micro_v2_stable_market_window",
    }
    for key in ("v2_log_dir", "base_log_dir", "reports_root", "checkpoint_dir", "readiness_dir", "filter_analysis_dir", "consolidated_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _init_db(paths["base_sqlite"])
    _heartbeat(paths["v2_sqlite"], stale=stale_heartbeat, connected=mt5_connected)
    for symbol in fresh:
        _event(paths["v2_sqlite"], "SYMBOL_ACCEPTED", symbol, {"symbol": symbol, "tick_time_status": "FRESH", "tick_age_seconds": 1}, old_hours=old_event_hours)
    if safety:
        _event(paths["v2_sqlite"], "SIGNAL_REJECTED", "EURUSD", {"execution_attempted": True})
    for idx in range(closed_trades):
        _trade(paths["v2_sqlite"], f"ptr{idx}", old_hours=max(1, old_event_hours))
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    (paths["base_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    paths["profile"].parent.mkdir(parents=True, exist_ok=True)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nSYMBOLS=EURUSD,GBPUSD,USDJPY\n", encoding="utf-8")
    total = 100
    market = int(total * market_ratio)
    _write_json(paths["filter_analysis_dir"] / "micro_v2_filter_analysis_summary.json", {"total_v2_rejections": total, "market_closed_rejection_count": market, "stale_tick_rejection_count": 0, "total_v2_signals": 100, "fresh_tick_symbols": fresh, "dominant_v2_filter": ""})
    _write_json(paths["checkpoint_dir"] / "micro_v2_observation_checkpoint_summary.json", {"v2_paper_trades_open": 0, "v2_paper_trades_closed": closed_trades, "fresh_tick_symbols": fresh, "v2_signals_detected": 100, "v2_signals_rejected": total})
    _write_json(paths["readiness_dir"] / "micro_v2_market_open_readiness_summary.json", {"fresh_tick_symbols": fresh, "stale_tick_symbols": []})
    _write_json(paths["consolidated_dir"] / "micro_v2_consolidated_audit_summary.json", {"market_closed_dominance_ratio": market_ratio})
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


def _heartbeat(path: Path, *, stale: bool, connected: bool) -> None:
    ts = datetime.now(timezone.utc) - timedelta(minutes=60 if stale else 0)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", ts.isoformat(), "forward-shadow", int(connected), 0, json.dumps({"mt5_connected": connected, "execution_attempted": False})),
        )
        conn.commit()
    finally:
        conn.close()


def _event(path: Path, event_type: str, symbol: str, payload: dict[str, object], *, old_hours: int = 0) -> None:
    ts = datetime.now(timezone.utc) - timedelta(hours=old_hours)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, symbol, ts.isoformat(), "INFO", event_type, json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _trade(path: Path, trade_id: str, *, old_hours: int) -> None:
    opened = datetime.now(timezone.utc) - timedelta(hours=old_hours)
    closed = datetime.now(timezone.utc)
    payload = {"paper_trade_id": trade_id, "symbol": "EURUSD", "status": "CLOSED"}
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, symbol, status, payload_json, opened_at_utc, closed_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (trade_id, "EURUSD", "CLOSED", json.dumps(payload), opened.isoformat(), closed.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
