from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_papertrade_schema_repair import run_micro_v2_papertrade_schema_repair
from agi_style_forex_bot_mt5.micro_v2_post_repair_resume_guard.manage_open_trades_only_policy import build_manage_open_trades_only_policy
from agi_style_forex_bot_mt5.paper_trading.paper_trade import EXTRA_FIELDS_METADATA_KEY, PaperTrade


def test_papertrade_loader_ignores_invalid_close() -> None:
    trade = PaperTrade.from_mapping({**_trade_payload("ptr_extra"), "invalid_close": True})
    assert trade.paper_trade_id == "ptr_extra"
    assert trade.metadata[EXTRA_FIELDS_METADATA_KEY]["invalid_close"] is True


def test_papertrade_loader_ignores_unknown_extra_fields() -> None:
    trade = PaperTrade.from_mapping({**_trade_payload("ptr_unknown"), "future_schema_field": "kept"})
    assert trade.metadata[EXTRA_FIELDS_METADATA_KEY]["future_schema_field"] == "kept"


def test_closed_paper_trade_conserves_realized_pnl() -> None:
    trade = PaperTrade.from_mapping(_trade_payload("ptr_closed", status="CLOSED", profit=1.25))
    assert trade.status == "CLOSED"
    assert trade.profit == 1.25
    assert trade.exit_time_utc is not None


def test_quarantined_trade_not_counted_as_closed(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_trade(paths["v2_sqlite"], {**_trade_payload("ptr_quar", status="QUARANTINED_INVALID_PAPER_TRADE"), "invalid_close": False})
    summary = run_micro_v2_papertrade_schema_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        resume_guard_dir=paths["resume_guard_dir"],
        repair_dir=paths["repair_dir"],
        output_dir=paths["out"],
    )
    assert summary["closed_trade_count"] == 0
    assert summary["quarantined_trade_count"] == 1
    assert summary["invalid_close_handled"] is True


def test_loader_handles_old_and_new_trades(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_trade(paths["v2_sqlite"], _trade_payload("ptr_old"))
    _insert_trade(paths["v2_sqlite"], {**_trade_payload("ptr_new"), "audit_flags": ["schema_v_next"]})
    summary = run_micro_v2_papertrade_schema_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        resume_guard_dir=paths["resume_guard_dir"],
        repair_dir=paths["repair_dir"],
        output_dir=paths["out"],
    )
    assert summary["micro_v2_papertrade_schema_repair_status"] == "MICRO_V2_PAPERTRADE_SCHEMA_NO_SQLITE_REPAIR_NEEDED"
    assert summary["extra_fields_detected"]["audit_flags"] == 1


def test_dry_run_does_not_modify_sqlite(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_trade(paths["v2_sqlite"], {**_trade_payload("ptr_extra"), "invalid_close": True})
    before = paths["v2_sqlite"].read_bytes()
    run_micro_v2_papertrade_schema_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        resume_guard_dir=paths["resume_guard_dir"],
        repair_dir=paths["repair_dir"],
        output_dir=paths["out"],
    )
    assert paths["v2_sqlite"].read_bytes() == before


def test_apply_creates_backup_if_modifying_sqlite(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_trade(paths["v2_sqlite"], {**_trade_payload("ptr_extra"), "invalid_close": True})
    summary = run_micro_v2_papertrade_schema_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        resume_guard_dir=paths["resume_guard_dir"],
        repair_dir=paths["repair_dir"],
        output_dir=paths["out"],
        apply_repair=True,
        backup_root=tmp_path / "data" / "backups" / "micro_v2_papertrade_schema_repair",
    )
    manifest = json.loads((paths["out"] / "sqlite_backup_manifest.json").read_text(encoding="utf-8"))
    assert summary["sqlite_repair_applied"] is True
    assert manifest["backup_created"] is True


def test_stable_sqlite_not_modified(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _init_db(paths["stable_sqlite"])
    before = paths["stable_sqlite"].read_bytes()
    _insert_trade(paths["v2_sqlite"], {**_trade_payload("ptr_extra"), "invalid_close": True})
    run_micro_v2_papertrade_schema_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        resume_guard_dir=paths["resume_guard_dir"],
        repair_dir=paths["repair_dir"],
        output_dir=paths["out"],
    )
    assert paths["stable_sqlite"].read_bytes() == before


def test_manage_only_blocks_new_entries_allows_exits() -> None:
    policy = build_manage_open_trades_only_policy(enabled=True, reason="phase67")
    assert policy["new_entries_blocked"] is True
    assert policy["paper_exit_evaluation_allowed"] is True


def test_no_order_send_order_check_and_safety_defaults() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False
    policy = build_manage_open_trades_only_policy(enabled=True, reason="phase67")
    assert policy["order_send_called"] is False
    assert policy["order_check_called"] is False
    assert policy["execution_attempted"] is False


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "stable_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "resume_guard_dir": tmp_path / "data" / "reports" / "micro_v2_post_repair_resume_guard",
        "repair_dir": tmp_path / "data" / "reports" / "micro_v2_guarded_paper_state_repair",
        "out": tmp_path / "data" / "reports" / "micro_v2_papertrade_schema_repair",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    return paths


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, signal_id TEXT, idempotency_key TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT, updated_at_utc TEXT)")
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)")
        conn.commit()
    finally:
        conn.close()


def _insert_trade(path: Path, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, signal_id, idempotency_key, symbol, status, payload_json, opened_at_utc, closed_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payload["paper_trade_id"],
                payload["signal_id"],
                payload["idempotency_key"],
                payload["symbol"],
                payload["status"],
                json.dumps(payload, sort_keys=True),
                payload["entry_time_utc"],
                payload.get("exit_time_utc"),
                payload["entry_time_utc"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _trade_payload(trade_id: str, *, status: str = "OPEN", profit: float = 0.0) -> dict[str, object]:
    closed = status.upper() == "CLOSED"
    return {
        "paper_trade_id": trade_id,
        "signal_id": f"sig_{trade_id}",
        "idempotency_key": f"paper_trade:{trade_id}",
        "symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "direction": "BUY",
        "entry_time_utc": "2026-06-01T00:00:00+00:00",
        "entry_price": 1.1,
        "sl_price": 1.099,
        "tp_price": 1.102,
        "lot": 0.01,
        "risk_pct": 0.01,
        "risk_amount": 1.0,
        "strategy_name": "strategy_ensemble",
        "strategy_version": "0.2.0",
        "regime": "LOW_VOLATILITY",
        "session": "LONDON",
        "score": 70.0,
        "reasons": ["test"],
        "status": status,
        "exit_time_utc": "2026-06-01T01:00:00+00:00" if closed else None,
        "exit_price": 1.101 if closed else None,
        "exit_reason": "TP" if closed else None,
        "profit": profit,
        "raw_pnl": profit,
        "scaled_paper_pnl": profit,
        "metadata": {},
    }
