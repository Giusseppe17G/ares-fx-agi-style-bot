from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_risk_block_audit import run_micro_v2_risk_block_audit


def test_cooldown_dominates(tmp_path: Path) -> None:
    _assert_status(tmp_path, "COOLDOWN_BLOCK", "MICRO_V2_RISK_BLOCK_COOLDOWN_DOMINATES")


def test_max_paper_trades_per_day_dominates(tmp_path: Path) -> None:
    _assert_status(tmp_path, "MAX_PAPER_TRADES_PER_DAY", "MICRO_V2_RISK_BLOCK_TRADE_LIMIT_DOMINATES")


def test_max_open_trades_dominates(tmp_path: Path) -> None:
    _assert_status(tmp_path, "MAX_OPEN_PAPER_TRADES", "MICRO_V2_RISK_BLOCK_MAX_OPEN_TRADES_DOMINATES")


def test_invalid_risk_distance(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    for _ in range(10):
        _risk(paths["v2_sqlite"], "INVALID_RISK_DISTANCE risk_distance <= 0")

    summary = _run(paths)

    assert summary["micro_v2_risk_block_status"] == "MICRO_V2_RISK_BLOCK_INVALID_RISK_DISTANCE"
    assert summary["dominant_risk_block_reason"] == "INVALID_RISK_DISTANCE"


def test_zero_position_size(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    for _ in range(10):
        _risk(paths["v2_sqlite"], "ZERO_POSITION_SIZE calculated volume 0")

    summary = _run(paths)

    assert summary["micro_v2_risk_block_status"] == "MICRO_V2_RISK_BLOCK_ZERO_POSITION_SIZE"


def test_not_enough_data(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    for _ in range(3):
        _risk(paths["v2_sqlite"], "COOLDOWN_BLOCK")

    summary = _run(paths)

    assert summary["micro_v2_risk_block_status"] == "MICRO_V2_RISK_BLOCK_NOT_ENOUGH_DATA"
    assert summary["risk_rejected_count"] == 3


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    for _ in range(10):
        _risk(paths["v2_sqlite"], "COOLDOWN_BLOCK")
    _risk(paths["v2_sqlite"], "COOLDOWN_BLOCK", extra={"execution_attempted": True})

    summary = _run(paths)

    assert summary["micro_v2_risk_block_status"] == "MICRO_V2_RISK_BLOCK_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_cli_does_not_modify_sqlite_logs_or_profile(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path)
    for _ in range(10):
        _risk(paths["v2_sqlite"], "COOLDOWN_BLOCK")
    sqlite_before = paths["v2_sqlite"].read_bytes()
    log_before = (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8")
    profile_before = paths["profile"].read_text(encoding="utf-8")

    result = cli.main(
        [
            "--mode",
            "micro-v2-risk-block-audit",
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
            "--filter-analysis-dir",
            str(paths["filter_analysis_dir"]),
            "--checkpoint-dir",
            str(paths["checkpoint_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["micro_v2_risk_block_status"] == "MICRO_V2_RISK_BLOCK_COOLDOWN_DOMINATES"
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert (paths["v2_log_dir"] / "events.jsonl").read_text(encoding="utf-8") == log_before
    assert paths["profile"].read_text(encoding="utf-8") == profile_before


def _assert_status(tmp_path: Path, reason: str, expected_status: str) -> None:
    paths = _fixture(tmp_path)
    for _ in range(7):
        _risk(paths["v2_sqlite"], reason)
    for _ in range(3):
        _risk(paths["v2_sqlite"], "EXPECTED_SAFETY_GUARD")

    summary = _run(paths)

    assert summary["micro_v2_risk_block_status"] == expected_status


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_risk_block_audit(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        filter_analysis_dir=paths["filter_analysis_dir"],
        checkpoint_dir=paths["checkpoint_dir"],
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
        "filter_analysis_dir": tmp_path / "data" / "reports" / "micro_v2_filter_analysis",
        "checkpoint_dir": tmp_path / "data" / "reports" / "micro_v2_observation_checkpoint",
        "out": tmp_path / "data" / "reports" / "micro_v2_risk_block_audit",
    }
    for key in ("v2_log_dir", "base_log_dir", "reports_root", "filter_analysis_dir", "checkpoint_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _init_db(paths["base_sqlite"])
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    (paths["base_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    paths["profile"].parent.mkdir(parents=True, exist_ok=True)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    (paths["filter_analysis_dir"] / "micro_v2_filter_analysis_summary.json").write_text(json.dumps({"dominant_v2_filter": "RISK_BLOCK"}), encoding="utf-8")
    (paths["checkpoint_dir"] / "micro_v2_observation_checkpoint_summary.json").write_text(json.dumps({"micro_v2_checkpoint_status": "MICRO_V2_CHECKPOINT_READY_FOR_FILTER_ANALYSIS"}), encoding="utf-8")
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


def _risk(path: Path, reason: str, *, extra: dict[str, object] | None = None) -> None:
    payload = {"symbol": "EURUSD", "reason": reason, "blocking_reasons": [reason], "session": "LONDON"}
    payload.update(extra or {})
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("RISK_REJECTED", "EURUSD", datetime.now(timezone.utc).isoformat(), "INFO", reason, json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()
