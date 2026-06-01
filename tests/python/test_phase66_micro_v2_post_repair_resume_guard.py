from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5.micro_v2_post_repair_resume_guard import run_micro_v2_post_repair_resume_guard
from agi_style_forex_bot_mt5.micro_v2_post_repair_resume_guard.manage_open_trades_only_policy import build_manage_open_trades_only_policy
from agi_style_forex_bot_mt5.micro_v2_post_repair_resume_guard.resume_guard_policy import evaluate_post_repair_resume_guard


def test_open_trades_invalid_zero_v2_enables_manage_only(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=4, invalid=False)
    summary = _run(paths)
    assert summary["micro_v2_post_repair_resume_guard_status"] == "MICRO_V2_POST_REPAIR_MANAGE_OPEN_TRADES_ONLY_ENABLED"
    assert summary["manage_open_trades_only_enabled"] is True
    assert summary["new_entries_blocked"] is True
    assert summary["paper_exit_evaluation_allowed"] is True


def test_invalid_open_trade_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=1, invalid=True)
    summary = _run(paths)
    assert summary["micro_v2_post_repair_resume_guard_status"] == "MICRO_V2_POST_REPAIR_BLOCKED_INVALID_OPEN_TRADES"


def test_profile_mismatch_blocks() -> None:
    policy = evaluate_post_repair_resume_guard(
        signal_profile="BALANCED_STABLE_MICRO",
        sqlite_path="data/sqlite/forward-shadow-v2-dryrun.sqlite3",
        profile_values={},
        lifecycle={"open_trade_count": 1, "invalid_open_trade_count": 0},
        safety_flags=False,
    )
    assert policy["micro_v2_post_repair_resume_guard_status"] == "MICRO_V2_POST_REPAIR_BLOCKED_PROFILE_MISMATCH"


def test_sqlite_scope_mismatch_blocks() -> None:
    policy = evaluate_post_repair_resume_guard(
        signal_profile="BALANCED_STABLE_MICRO_V2",
        sqlite_path="data/sqlite/forward-shadow-stable.sqlite3",
        profile_values={},
        lifecycle={"open_trade_count": 1, "invalid_open_trade_count": 0},
        safety_flags=False,
    )
    assert policy["micro_v2_post_repair_resume_guard_status"] == "MICRO_V2_POST_REPAIR_BLOCKED_SQLITE_SCOPE_MISMATCH"


def test_no_open_trades_blocks_no_need(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=0, invalid=False)
    summary = _run(paths)
    assert summary["micro_v2_post_repair_resume_guard_status"] == "MICRO_V2_POST_REPAIR_BLOCKED_NO_OPEN_TRADES"


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=1, invalid=False, safety=True)
    summary = _run(paths)
    assert summary["micro_v2_post_repair_resume_guard_status"] == "MICRO_V2_POST_REPAIR_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False


def test_manage_only_policy_blocks_new_entries_allows_exit_eval() -> None:
    policy = build_manage_open_trades_only_policy(enabled=True, reason="test")
    assert policy["new_entries_blocked"] is True
    assert policy["new_paper_trades_blocked"] is True
    assert policy["paper_exit_evaluation_allowed"] is True
    assert policy["order_send_called"] is False
    assert policy["order_check_called"] is False


def test_stable_profile_behavior_unchanged() -> None:
    policy = evaluate_post_repair_resume_guard(
        signal_profile="BALANCED_STABLE_MICRO",
        sqlite_path="data/sqlite/forward-shadow-stable.sqlite3",
        profile_values={},
        lifecycle={"open_trade_count": 4, "invalid_open_trade_count": 0},
        safety_flags=False,
    )
    assert policy["accepted"] is False
    assert policy["manage_open_trades_only_enabled"] is False


def test_stable_sqlite_not_modified(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, open_trades=4, invalid=False)
    before = paths["base_sqlite"].read_bytes()
    _run(paths)
    assert paths["base_sqlite"].read_bytes() == before


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_post_repair_resume_guard(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        repair_dir=paths["repair_dir"],
        lifecycle_dir=paths["lifecycle_dir"],
        daily_risk_ledger=paths["daily_risk_ledger"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path, *, open_trades: int, invalid: bool, safety: bool = False) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "repair_dir": tmp_path / "data" / "reports" / "micro_v2_guarded_paper_state_repair",
        "lifecycle_dir": tmp_path / "data" / "reports" / "micro_v2_lifecycle_risk_comparison",
        "daily_risk_ledger": tmp_path / "data" / "reports" / "paper_daily_risk" / "paper_daily_risk_ledger.json",
        "out": tmp_path / "data" / "reports" / "micro_v2_post_repair_resume_guard",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _init_db(paths["base_sqlite"])
    for index in range(open_trades):
        _insert_trade(paths["v2_sqlite"], f"ptr{index}", invalid=invalid and index == 0)
    if safety:
        _heartbeat(paths["v2_sqlite"], safety=True)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nSIGNAL_PROFILE=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    paths["daily_risk_ledger"].write_text(json.dumps({"daily_risk_ledger_status": "DAILY_RISK_LEDGER_ACCEPTED"}), encoding="utf-8")
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    (paths["base_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    (paths["repair_dir"] / "repair_after_snapshot.json").write_text(json.dumps({"quarantined_trade_count": 1}), encoding="utf-8")
    (paths["repair_dir"] / "micro_v2_guarded_paper_state_repair_summary.json").write_text(json.dumps({"repair_applied": True}), encoding="utf-8")
    (paths["lifecycle_dir"] / "micro_v2_lifecycle_risk_comparison_summary.json").write_text(json.dumps({"open_trade_count": open_trades}), encoding="utf-8")
    return paths


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT)")
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)")
        conn.commit()
    finally:
        conn.close()


def _insert_trade(path: Path, trade_id: str, *, invalid: bool) -> None:
    entry = 1.1
    sl = 1.1 if invalid else 1.099
    payload = {"paper_trade_id": trade_id, "symbol": "EURUSD", "entry_price": entry, "sl_price": sl, "tp_price": 1.102, "side": "BUY", "status": "OPEN"}
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, symbol, status, payload_json, opened_at_utc, closed_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (trade_id, "EURUSD", "OPEN", json.dumps(payload), datetime.now(timezone.utc).isoformat(), ""),
        )
        conn.commit()
    finally:
        conn.close()


def _heartbeat(path: Path, *, safety: bool) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", datetime.now(timezone.utc).isoformat(), "forward-shadow", 1, int(safety), json.dumps({"execution_attempted": safety})),
        )
        conn.commit()
    finally:
        conn.close()
