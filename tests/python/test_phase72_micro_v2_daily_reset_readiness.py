from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5.cli import main
from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_daily_reset_readiness import run_micro_v2_daily_reset_readiness


NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def test_halt_active_same_day_not_ready(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, halt_time=NOW)
    summary = _run(paths)

    assert summary["micro_v2_daily_reset_readiness_status"] == "MICRO_V2_DAILY_RESET_NOT_READY_KEEP_HALTED"
    assert summary["daily_halt_active"] is True
    assert summary["relaunch_allowed"] is False


def test_halt_expired_and_scope_ok_ready_for_relaunch(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, halt_time=NOW - timedelta(days=1), ledger_time=NOW - timedelta(days=1))
    summary = _run(paths)

    assert summary["micro_v2_daily_reset_readiness_status"] == "MICRO_V2_DAILY_RESET_READY_FOR_RELAUNCH"
    assert summary["daily_halt_active"] is False
    assert summary["daily_risk_scope_status"] == "DAILY_RISK_SCOPE_OK_FOR_V2"
    assert summary["relaunch_allowed"] is True
    assert "forward-shadow" in summary["relaunch_command"]


def test_scope_invalid_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, halt_time=NOW - timedelta(days=1), include_v2_scope=False)
    summary = _run(paths)

    assert summary["micro_v2_daily_reset_readiness_status"] == "MICRO_V2_DAILY_RESET_SCOPE_INVALID"
    assert summary["relaunch_allowed"] is False


def test_open_trades_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, halt_time=NOW - timedelta(days=1), open_trade=True)
    summary = _run(paths)

    assert summary["micro_v2_daily_reset_readiness_status"] == "MICRO_V2_DAILY_RESET_OPEN_TRADES_BLOCK"
    assert summary["open_trade_count"] == 1


def test_invalid_open_trades_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, halt_time=NOW - timedelta(days=1), invalid_open_trade=True)
    summary = _run(paths)

    assert summary["micro_v2_daily_reset_readiness_status"] == "MICRO_V2_DAILY_RESET_INVALID_TRADES_BLOCK"
    assert summary["invalid_open_trade_count"] == 1


def test_paper_state_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, halt_time=NOW - timedelta(days=1), paper_state_error=True)
    summary = _run(paths)

    assert summary["micro_v2_daily_reset_readiness_status"] == "MICRO_V2_DAILY_RESET_PAPER_STATE_BLOCK"
    assert summary["paper_state_clean_for_relaunch"] is False


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, halt_time=NOW - timedelta(days=1), safety_flag=True)
    summary = _run(paths)

    assert summary["micro_v2_daily_reset_readiness_status"] == "MICRO_V2_DAILY_RESET_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_no_sqlite_or_ledger_mutation(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, halt_time=NOW - timedelta(days=1))
    sqlite_before = paths["v2_sqlite"].read_bytes()
    ledger_before = paths["daily_ledger"].read_text(encoding="utf-8")
    _run(paths)

    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert paths["daily_ledger"].read_text(encoding="utf-8") == ledger_before


def test_cli_mode_exists(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, halt_time=datetime.now(timezone.utc))
    code = main(
        [
            "--mode",
            "micro-v2-daily-reset-readiness",
            "--v2-sqlite",
            str(paths["v2_sqlite"]),
            "--v2-log-dir",
            str(paths["v2_log_dir"]),
            "--reports-root",
            str(paths["reports_root"]),
            "--v2-profile-config",
            str(paths["profile"]),
            "--daily-risk-ledger",
            str(paths["daily_ledger"]),
            "--daily-risk-scope-repair-dir",
            str(paths["scope_repair_dir"]),
            "--closed-loss-scope-dir",
            str(paths["closed_loss_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert code == 0
    assert (paths["out"] / "micro_v2_daily_reset_readiness_summary.json").exists()


def test_no_order_send_order_check_and_config_safety() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_daily_reset_readiness(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        daily_risk_ledger=paths["daily_ledger"],
        daily_risk_scope_repair_dir=paths["scope_repair_dir"],
        closed_loss_scope_dir=paths["closed_loss_dir"],
        output_dir=paths["out"],
        current_utc=NOW,
    )


def _fixture(
    tmp_path: Path,
    *,
    halt_time: datetime,
    ledger_time: datetime | None = None,
    include_v2_scope: bool = True,
    open_trade: bool = False,
    invalid_open_trade: bool = False,
    paper_state_error: bool = False,
    safety_flag: bool = False,
) -> dict[str, Path]:
    ledger_time = ledger_time or NOW - timedelta(hours=1)
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "daily_ledger": tmp_path / "data" / "reports" / "paper_daily_risk" / "paper_daily_risk_ledger.json",
        "scope_repair_dir": tmp_path / "data" / "reports" / "micro_v2_daily_risk_scope_repair",
        "closed_loss_dir": tmp_path / "data" / "reports" / "micro_v2_closed_loss_scope_decision",
        "out": tmp_path / "data" / "reports" / "micro_v2_daily_reset_readiness",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _insert_halt(paths["v2_sqlite"], halt_time)
    for index in range(3):
        _insert_trade(paths["v2_sqlite"], f"ptr_q_{index}", "QUARANTINED_INVALID_PAPER_TRADE", entry=1.1, sl=1.1, tp=1.2)
    if open_trade:
        _insert_trade(paths["v2_sqlite"], "ptr_open", "OPEN", entry=1.1, sl=1.0, tp=1.2)
    if invalid_open_trade:
        _insert_trade(paths["v2_sqlite"], "ptr_invalid", "OPEN", entry=1.1, sl=1.1, tp=1.2)
    if paper_state_error:
        _insert_error(paths["v2_sqlite"], ledger_time + timedelta(minutes=10), "CONFIG_ERROR")
    if safety_flag:
        _insert_heartbeat(paths["v2_sqlite"], execution_attempted=True)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    entries = [_entry("BALANCED_STABLE_MICRO", paths["v2_sqlite"], ledger_time)]
    if include_v2_scope:
        entries.append(_entry("BALANCED_STABLE_MICRO_V2", paths["v2_sqlite"], ledger_time))
    paths["daily_ledger"].write_text(json.dumps({"daily_risk_clearances": entries, "execution_attempted": False}, indent=2), encoding="utf-8")
    (paths["scope_repair_dir"] / "micro_v2_daily_risk_scope_repair_summary.json").write_text(json.dumps({"daily_risk_scope_status_after": "DAILY_RISK_SCOPE_OK_FOR_V2"}), encoding="utf-8")
    (paths["closed_loss_dir"] / "micro_v2_closed_loss_scope_decision_summary.json").write_text(json.dumps({"closed_scaled_pnl_total": -9.996, "closed_trade_count": 2}), encoding="utf-8")
    return paths


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)")
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT UNIQUE, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT)")
        conn.commit()
    finally:
        conn.close()


def _insert_halt(path: Path, timestamp: datetime) -> None:
    conn = sqlite3.connect(path)
    try:
        payload = {"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT", "execution_attempted": False}
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("PAPER_SHADOW_HALTED", "USDJPY", timestamp.isoformat(), "CRITICAL", "paper_shadow_halted", json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_error(path: Path, timestamp: datetime, error: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("FORWARD_SHADOW_CRITICAL_ERROR", "", timestamp.isoformat(), "CRITICAL", "forward_shadow_critical_error", json.dumps({"error": error, "execution_attempted": False})),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_heartbeat(path: Path, *, execution_attempted: bool) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", NOW.isoformat(), "forward-shadow", 1, int(execution_attempted), json.dumps({"execution_attempted": execution_attempted})),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_trade(path: Path, trade_id: str, status: str, *, entry: float, sl: float, tp: float) -> None:
    payload = {"paper_trade_id": trade_id, "symbol": "USDJPY", "status": status, "entry_price": entry, "sl_price": sl, "tp_price": tp}
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, symbol, status, payload_json, opened_at_utc, closed_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (trade_id, "USDJPY", status, json.dumps(payload), NOW.isoformat(), None),
        )
        conn.commit()
    finally:
        conn.close()


def _entry(profile: str, sqlite_path: Path, created: datetime) -> dict[str, object]:
    return {
        "daily_risk_clearance_id": f"pdrc_{profile.lower()}",
        "canonical_cleared_for_profile": profile,
        "cleared_for_profile": profile,
        "created_at_utc": created.isoformat(),
        "sqlite_scope": str(Path(str(sqlite_path))).replace("/", "\\"),
        "daily_halt_active": True,
        "closed_scaled_pnl_total": -9.996,
        "closed_trade_count": 2,
        "quarantined_trade_count": 3,
        "active_halts_cleared": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
