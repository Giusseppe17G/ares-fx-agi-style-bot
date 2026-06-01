from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_guarded_open_trade_integrity_repair import run_micro_v2_guarded_open_trade_integrity_repair


TARGETS = ("ptr_55f75f721d4340a6b4814ae9e76989f9", "ptr_40ff07bf568b4818b294efeaf74923dd")


def test_dry_run_does_not_modify_sqlite(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    before = paths["v2_sqlite"].read_bytes()
    summary = _run(paths)
    assert summary["micro_v2_guarded_open_trade_integrity_repair_status"] == "MICRO_V2_OPEN_TRADE_REPAIR_DRY_RUN_READY"
    assert paths["v2_sqlite"].read_bytes() == before


def test_apply_creates_backup_and_quarantines(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = run_micro_v2_guarded_open_trade_integrity_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        drawdown_recovery_dir=paths["drawdown_dir"],
        schema_repair_dir=paths["schema_dir"],
        previous_repair_dir=paths["previous_repair_dir"],
        output_dir=paths["out"],
        backup_root=tmp_path / "data" / "backups" / "micro_v2_guarded_open_trade_integrity_repair",
        apply_repair=True,
    )
    assert summary["micro_v2_guarded_open_trade_integrity_repair_status"] == "MICRO_V2_OPEN_TRADE_REPAIR_APPLIED_SUCCESSFULLY"
    assert summary["backup_created"] is True
    assert summary["closed_trade_count_changed"] is False
    assert summary["pnl_changed"] is False
    assert summary["invalid_open_trade_count_after"] == 0
    assert summary["open_trade_count_after"] == 0
    assert summary["quarantined_trade_count_after"] == 2


def test_runtime_active_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _heartbeat(paths["v2_sqlite"])
    summary = run_micro_v2_guarded_open_trade_integrity_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        drawdown_recovery_dir=paths["drawdown_dir"],
        schema_repair_dir=paths["schema_dir"],
        previous_repair_dir=paths["previous_repair_dir"],
        output_dir=paths["out"],
        apply_repair=True,
    )
    assert summary["micro_v2_guarded_open_trade_integrity_repair_status"] == "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_RUNTIME_ACTIVE"


def test_plan_mismatch_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, symbol="EURUSD")
    summary = _run(paths)
    assert summary["micro_v2_guarded_open_trade_integrity_repair_status"] == "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_PLAN_MISMATCH"


def test_trade_not_found_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _replace_plan(paths["drawdown_dir"], ["missing"])
    summary = _run(paths)
    assert summary["micro_v2_guarded_open_trade_integrity_repair_status"] == "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_TRADE_NOT_FOUND"


def test_trade_already_closed_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, status="CLOSED")
    summary = _run(paths)
    assert summary["micro_v2_guarded_open_trade_integrity_repair_status"] == "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_TRADE_ALREADY_CLOSED"


def test_unsafe_repair_action_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, pnl=1.0)
    summary = _run(paths)
    assert summary["micro_v2_guarded_open_trade_integrity_repair_status"] == "MICRO_V2_OPEN_TRADE_REPAIR_BLOCKED_UNSAFE_ACTION"


def test_stable_sqlite_not_modified(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _init_db(paths["stable_sqlite"])
    before = paths["stable_sqlite"].read_bytes()
    run_micro_v2_guarded_open_trade_integrity_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        drawdown_recovery_dir=paths["drawdown_dir"],
        schema_repair_dir=paths["schema_dir"],
        previous_repair_dir=paths["previous_repair_dir"],
        output_dir=paths["out"],
        apply_repair=True,
        backup_root=tmp_path / "data" / "backups" / "micro_v2_guarded_open_trade_integrity_repair",
    )
    assert paths["stable_sqlite"].read_bytes() == before


def test_no_profiles_modified(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    before = paths["profile"].read_text(encoding="utf-8")
    _run(paths)
    assert paths["profile"].read_text(encoding="utf-8") == before


def test_no_order_send_order_check_and_config_safety() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_guarded_open_trade_integrity_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        drawdown_recovery_dir=paths["drawdown_dir"],
        schema_repair_dir=paths["schema_dir"],
        previous_repair_dir=paths["previous_repair_dir"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path, *, symbol: str = "USDJPY", status: str = "OPEN", pnl: float = 0.0) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "stable_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "drawdown_dir": tmp_path / "data" / "reports" / "micro_v2_daily_drawdown_state_recovery",
        "schema_dir": tmp_path / "data" / "reports" / "micro_v2_papertrade_schema_repair",
        "previous_repair_dir": tmp_path / "data" / "reports" / "micro_v2_guarded_paper_state_repair",
        "out": tmp_path / "data" / "reports" / "micro_v2_guarded_open_trade_integrity_repair",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    for index, trade_id in enumerate(TARGETS):
        _insert_trade(paths["v2_sqlite"], trade_id, symbol=symbol, status=status, entry=159.401 + index * 0.002, pnl=pnl)
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    _write_phase68(paths["drawdown_dir"], symbol=symbol, target_ids=list(TARGETS))
    return paths


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT UNIQUE, signal_id TEXT, idempotency_key TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT, updated_at_utc TEXT)")
        conn.execute("CREATE TABLE paper_trade_events (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, event_type TEXT, timestamp_utc TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)")
        conn.commit()
    finally:
        conn.close()


def _insert_trade(path: Path, trade_id: str, *, symbol: str, status: str, entry: float, pnl: float) -> None:
    payload = {
        "paper_trade_id": trade_id,
        "signal_id": f"sig_{trade_id}",
        "idempotency_key": f"paper_trade:{trade_id}",
        "symbol": symbol,
        "broker_symbol": symbol,
        "direction": "BUY",
        "entry_time_utc": "2026-06-01T00:00:00+00:00",
        "entry_price": entry,
        "sl_price": entry,
        "tp_price": entry + 0.2,
        "status": status,
        "profit": pnl,
        "raw_pnl": pnl,
        "scaled_paper_pnl": pnl,
    }
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, signal_id, idempotency_key, symbol, status, payload_json, opened_at_utc, closed_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade_id, payload["signal_id"], payload["idempotency_key"], symbol, status, json.dumps(payload), payload["entry_time_utc"], None, payload["entry_time_utc"]),
        )
        conn.commit()
    finally:
        conn.close()


def _write_phase68(path: Path, *, symbol: str, target_ids: list[str]) -> None:
    rows = [
        {"paper_trade_id": trade_id, "symbol": symbol, "entry_price": 159.401, "sl_price": 159.401, "tp_price": 159.58, "reason": "ZERO_RISK_DISTANCE_ENTRY_EQUALS_SL"}
        for trade_id in target_ids
    ]
    (path / "open_trade_integrity_audit.json").write_text(json.dumps({"invalid_open_trade_count": len(rows), "invalid_open_trade_reasons": rows}), encoding="utf-8")
    (path / "micro_v2_daily_drawdown_state_recovery_summary.json").write_text(json.dumps({"drawdown_halt_root_cause": "OPEN_TRADE_INTEGRITY_ISSUE"}), encoding="utf-8")


def _replace_plan(path: Path, target_ids: list[str]) -> None:
    _write_phase68(path, symbol="USDJPY", target_ids=target_ids)


def _heartbeat(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", now, "forward-shadow", 1, 0, json.dumps({"timestamp_utc": now, "execution_attempted": False})),
        )
        conn.commit()
    finally:
        conn.close()
