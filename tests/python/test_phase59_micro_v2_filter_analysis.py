from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_filter_analysis import run_micro_v2_filter_analysis


def test_fresh_tick_absent_not_enough_data(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"])
    _reject(paths["v2_sqlite"], "SIGNAL_REJECTED", "EURUSD", "REGIME_BLOCK")

    summary = _run(paths)

    assert summary["micro_v2_filter_analysis_status"] == "MICRO_V2_FILTER_ANALYSIS_NOT_ENOUGH_FRESH_TICK_DATA"


def test_market_closed_dominates(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _fresh(paths["v2_sqlite"])
    for _ in range(8):
        _reject(paths["v2_sqlite"], "MARKET_CLOSED_REJECTION", "EURUSD", "MARKET_CLOSED_REJECTION")
    _reject(paths["v2_sqlite"], "SIGNAL_REJECTED", "EURUSD", "REGIME_BLOCK")

    summary = _run(paths)

    assert summary["micro_v2_filter_analysis_status"] == "MICRO_V2_FILTER_ANALYSIS_MARKET_CLOSED_DOMINATES"


def test_stale_ticks_dominate(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _fresh(paths["v2_sqlite"])
    for _ in range(8):
        _reject(paths["v2_sqlite"], "STALE_TICK_REJECTION", "EURUSD", "STALE_TICK_REJECTION")
    _reject(paths["v2_sqlite"], "SIGNAL_REJECTED", "EURUSD", "REGIME_BLOCK")

    summary = _run(paths)

    assert summary["micro_v2_filter_analysis_status"] == "MICRO_V2_FILTER_ANALYSIS_STALE_TICKS_DOMINATE"


def test_regime_dominates(tmp_path: Path) -> None:
    _assert_dominates(tmp_path, "REGIME_BLOCK", "MICRO_V2_FILTER_ANALYSIS_REGIME_BLOCK_DOMINATES")


def test_liquidity_dominates(tmp_path: Path) -> None:
    _assert_dominates(tmp_path, "LIQUIDITY_BLOCK", "MICRO_V2_FILTER_ANALYSIS_LIQUIDITY_BLOCK_DOMINATES")


def test_spread_dominates(tmp_path: Path) -> None:
    _assert_dominates(tmp_path, "SPREAD_BLOCK", "MICRO_V2_FILTER_ANALYSIS_SPREAD_BLOCK_DOMINATES")


def test_score_dominates(tmp_path: Path) -> None:
    _assert_dominates(tmp_path, "SCORE_THRESHOLD_BLOCK", "MICRO_V2_FILTER_ANALYSIS_SCORE_THRESHOLD_DOMINATES")


def test_cooldown_dominates(tmp_path: Path) -> None:
    _assert_dominates(tmp_path, "COOLDOWN_BLOCK", "MICRO_V2_FILTER_ANALYSIS_COOLDOWN_DOMINATES")


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _fresh(paths["v2_sqlite"])
    _reject(paths["v2_sqlite"], "SIGNAL_REJECTED", "EURUSD", "REGIME_BLOCK", extra={"execution_attempted": True})

    summary = _run(paths)

    assert summary["micro_v2_filter_analysis_status"] == "MICRO_V2_FILTER_ANALYSIS_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_candidate_is_research_only_and_runtime_false(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _fresh(paths["v2_sqlite"])
    for _ in range(5):
        _reject(paths["v2_sqlite"], "SIGNAL_REJECTED", "EURUSD", "REGIME_BLOCK")

    summary = _run(paths)
    candidate = json.loads((paths["out"] / "filter_tuning_candidate.json").read_text(encoding="utf-8"))

    assert summary["filter_tuning_candidate_available"] is True
    assert candidate["NOT_ACTIVE_RESEARCH_ONLY"] is True
    assert candidate["REQUIRES_REVIEW_PHASE"] is True
    assert candidate["APPROVED_FOR_RUNTIME"] is False


def test_cli_does_not_modify_sqlite_logs_or_profile(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path)
    _fresh(paths["v2_sqlite"])
    _reject(paths["v2_sqlite"], "SIGNAL_REJECTED", "EURUSD", "REGIME_BLOCK")
    sqlite_before = paths["v2_sqlite"].read_bytes()
    log_before = (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8")
    profile_before = paths["profile"].read_text(encoding="utf-8")

    result = cli.main(
        [
            "--mode",
            "micro-v2-filter-analysis",
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
            "--monitor-dir",
            str(paths["monitor_dir"]),
            "--readiness-dir",
            str(paths["readiness_dir"]),
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


def _assert_dominates(tmp_path: Path, reason: str, expected_status: str) -> None:
    paths = _fixture(tmp_path)
    _fresh(paths["v2_sqlite"])
    for _ in range(5):
        _reject(paths["v2_sqlite"], "SIGNAL_REJECTED", "EURUSD", reason)
    _reject(paths["v2_sqlite"], "SIGNAL_REJECTED", "EURUSD", "OTHER_FILTER")

    summary = _run(paths)

    assert summary["micro_v2_filter_analysis_status"] == expected_status
    assert summary["dominant_v2_filter"] == reason


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_filter_analysis(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        checkpoint_dir=paths["checkpoint_dir"],
        monitor_dir=paths["monitor_dir"],
        readiness_dir=paths["readiness_dir"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "checkpoint_dir": tmp_path / "data" / "reports" / "micro_v2_observation_checkpoint",
        "monitor_dir": tmp_path / "data" / "reports" / "micro_v2_dry_run_monitor",
        "readiness_dir": tmp_path / "data" / "reports" / "micro_v2_market_open_readiness",
        "out": tmp_path / "data" / "reports" / "micro_v2_filter_analysis",
    }
    for key in ("v2_log_dir", "base_log_dir", "reports_root", "checkpoint_dir", "monitor_dir", "readiness_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _init_db(paths["base_sqlite"])
    _heartbeat(paths["base_sqlite"])
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


def _heartbeat(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", datetime.now(timezone.utc).isoformat(), "forward-shadow", 1, 0, json.dumps({"mt5_connected": True, "execution_attempted": False})),
        )
        conn.commit()
    finally:
        conn.close()


def _fresh(path: Path) -> None:
    _heartbeat(path)
    _event(path, "SYMBOL_ACCEPTED", "EURUSD", {"symbol": "EURUSD", "tick_time_status": "FRESH", "tick_age_seconds": 1})


def _reject(path: Path, event_type: str, symbol: str, reason: str, *, extra: dict[str, object] | None = None) -> None:
    payload = {"symbol": symbol, "reason": reason, "blocking_reasons": [reason]}
    payload.update(extra or {})
    _event(path, event_type, symbol, payload)


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
