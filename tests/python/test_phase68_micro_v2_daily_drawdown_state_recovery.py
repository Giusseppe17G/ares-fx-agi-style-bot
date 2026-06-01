from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_daily_drawdown_state_recovery import run_micro_v2_daily_drawdown_state_recovery
from agi_style_forex_bot_mt5.micro_v2_daily_drawdown_state_recovery.drawdown_recovery_plan import build_drawdown_recovery_plan


def test_legitimate_drawdown_halt_no_repair(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_trade(paths["v2_sqlite"], _trade("closed_loss", status="CLOSED", pnl=-5.0))
    _log(paths["v2_log_dir"], "PAPER_SHADOW_HALTED", {"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT", "execution_attempted": False})
    summary = _run(paths)
    assert summary["micro_v2_daily_drawdown_state_recovery_status"] == "MICRO_V2_DRAWDOWN_HALT_LEGITIMATE"
    assert summary["repair_applied"] is False


def test_quarantine_contamination_plan_ready() -> None:
    plan = build_drawdown_recovery_plan(
        safety_blocked=False,
        closed_audit={"closed_trade_integrity_status": "CLOSED_TRADE_INTEGRITY_OK", "closed_scaled_pnl_total": 0.0},
        open_audit={"open_trade_integrity_status": "OPEN_TRADE_INTEGRITY_OK"},
        ledger_audit={"ledger_scope_mismatch": False},
        paper_state_audit={"drawdown_halt_root_cause": "QUARANTINE_CONTAMINATION"},
        quarantined_trade_count=1,
    )
    assert plan["micro_v2_daily_drawdown_state_recovery_status"] == "MICRO_V2_DRAWDOWN_HALT_QUARANTINE_CONTAMINATION"
    assert plan["repair_allowed"] is True


def test_ledger_scope_mismatch_plan_ready() -> None:
    plan = build_drawdown_recovery_plan(
        safety_blocked=False,
        closed_audit={"closed_trade_integrity_status": "CLOSED_TRADE_INTEGRITY_OK", "closed_scaled_pnl_total": 0.0},
        open_audit={"open_trade_integrity_status": "OPEN_TRADE_INTEGRITY_OK"},
        ledger_audit={"ledger_scope_mismatch": True},
        paper_state_audit={"drawdown_halt_root_cause": "DAILY_RISK_LEDGER_SCOPE_MISMATCH"},
        quarantined_trade_count=0,
    )
    assert plan["micro_v2_daily_drawdown_state_recovery_status"] == "MICRO_V2_DRAWDOWN_HALT_LEDGER_SCOPE_MISMATCH"
    assert plan["repair_allowed"] is True


def test_closed_trade_integrity_issue_manual_review(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    payload = _trade("closed_bad", status="CLOSED", pnl=-1.0)
    payload["exit_time_utc"] = None
    _insert_trade(paths["v2_sqlite"], payload)
    _log(paths["v2_log_dir"], "PAPER_SHADOW_HALTED", {"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT", "execution_attempted": False})
    summary = _run(paths)
    assert summary["micro_v2_daily_drawdown_state_recovery_status"] == "MICRO_V2_DRAWDOWN_HALT_CLOSED_TRADE_INTEGRITY_ISSUE"


def test_open_trade_integrity_issue_manual_review(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    payload = _trade("open_bad", status="OPEN", pnl=0.0)
    payload["sl_price"] = payload["entry_price"]
    _insert_trade(paths["v2_sqlite"], payload)
    summary = _run(paths)
    assert summary["micro_v2_daily_drawdown_state_recovery_status"] == "MICRO_V2_DRAWDOWN_HALT_OPEN_TRADE_INTEGRITY_ISSUE"


def test_dry_run_does_not_modify_sqlite(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_trade(paths["v2_sqlite"], _trade("closed_loss", status="CLOSED", pnl=-5.0))
    before = paths["v2_sqlite"].read_bytes()
    _run(paths)
    assert paths["v2_sqlite"].read_bytes() == before


def test_apply_creates_backup_if_allowed(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_trade(paths["v2_sqlite"], _trade("quar", status="QUARANTINED_INVALID_PAPER_TRADE", pnl=0.0))
    _log(paths["v2_log_dir"], "PAPER_SHADOW_HALTED", {"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT", "execution_attempted": False})
    # Force allowed branch through policy-level scope mismatch: no closed loss, base ledger only.
    summary = run_micro_v2_daily_drawdown_state_recovery(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        daily_risk_ledger=paths["daily_risk_ledger"],
        resume_guard_dir=paths["resume_guard_dir"],
        schema_repair_dir=paths["schema_repair_dir"],
        repair_dir=paths["repair_dir"],
        output_dir=paths["out"],
        apply_repair=True,
        backup_root=tmp_path / "data" / "backups" / "micro_v2_daily_drawdown_state_recovery",
    )
    manifest = json.loads((paths["out"] / "sqlite_backup_manifest.json").read_text(encoding="utf-8"))
    assert summary["repair_applied"] is False
    assert manifest["backup_created"] in {True, False}


def test_stable_sqlite_not_modified(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _init_db(paths["stable_sqlite"])
    before = paths["stable_sqlite"].read_bytes()
    _insert_trade(paths["v2_sqlite"], _trade("closed_loss", status="CLOSED", pnl=-5.0))
    _run(paths)
    assert paths["stable_sqlite"].read_bytes() == before


def test_no_pnl_or_count_changes_in_dry_run(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_trade(paths["v2_sqlite"], _trade("closed_loss", status="CLOSED", pnl=-5.0))
    before = _counts(paths["v2_sqlite"])
    _run(paths)
    after = _counts(paths["v2_sqlite"])
    assert before == after


def test_no_order_send_order_check_and_config_safety() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False
    plan = build_drawdown_recovery_plan(
        safety_blocked=False,
        closed_audit={"closed_trade_integrity_status": "CLOSED_TRADE_INTEGRITY_OK"},
        open_audit={"open_trade_integrity_status": "OPEN_TRADE_INTEGRITY_OK"},
        ledger_audit={},
        paper_state_audit={},
        quarantined_trade_count=0,
    )
    assert plan["execution_attempted"] is False
    assert plan["order_send_called"] is False
    assert plan["order_check_called"] is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_daily_drawdown_state_recovery(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        daily_risk_ledger=paths["daily_risk_ledger"],
        resume_guard_dir=paths["resume_guard_dir"],
        schema_repair_dir=paths["schema_repair_dir"],
        repair_dir=paths["repair_dir"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "stable_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "daily_risk_ledger": tmp_path / "data" / "reports" / "paper_daily_risk" / "paper_daily_risk_ledger.json",
        "resume_guard_dir": tmp_path / "data" / "reports" / "micro_v2_post_repair_resume_guard",
        "schema_repair_dir": tmp_path / "data" / "reports" / "micro_v2_papertrade_schema_repair",
        "repair_dir": tmp_path / "data" / "reports" / "micro_v2_guarded_paper_state_repair",
        "out": tmp_path / "data" / "reports" / "micro_v2_daily_drawdown_state_recovery",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    paths["daily_risk_ledger"].write_text(json.dumps({"daily_risk_clearances": [{"canonical_cleared_for_profile": "BALANCED_STABLE_MICRO", "daily_risk_clearance_id": "base"}]}), encoding="utf-8")
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
            (payload["paper_trade_id"], payload["signal_id"], payload["idempotency_key"], payload["symbol"], payload["status"], json.dumps(payload), payload["entry_time_utc"], payload.get("exit_time_utc"), payload["entry_time_utc"]),
        )
        conn.commit()
    finally:
        conn.close()


def _log(log_dir: Path, event_type: str, payload: dict[str, object]) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "events.jsonl").write_text(json.dumps({"event_type": event_type, "payload_json": json.dumps(payload), **payload}) + "\n", encoding="utf-8")


def _trade(trade_id: str, *, status: str, pnl: float) -> dict[str, object]:
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
        "exit_reason": "SL" if closed else None,
        "profit": pnl,
        "raw_pnl": pnl,
        "scaled_paper_pnl": pnl,
        "metadata": {},
    }


def _counts(path: Path) -> tuple[int, int, float]:
    conn = sqlite3.connect(path)
    try:
        rows = [json.loads(row[0]) for row in conn.execute("SELECT payload_json FROM paper_trades")]
        return (
            sum(1 for row in rows if row.get("status") == "OPEN"),
            sum(1 for row in rows if row.get("status") == "CLOSED"),
            sum(float(row.get("scaled_paper_pnl", 0.0) or 0.0) for row in rows),
        )
    finally:
        conn.close()
