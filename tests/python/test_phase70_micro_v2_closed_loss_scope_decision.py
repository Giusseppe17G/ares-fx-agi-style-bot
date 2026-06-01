from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agi_style_forex_bot_mt5.cli import main
from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_closed_loss_scope_decision import run_micro_v2_closed_loss_scope_decision
from agi_style_forex_bot_mt5.micro_v2_closed_loss_scope_decision.daily_risk_scope_audit import audit_daily_risk_scope


def test_closed_losses_legitimate_keep_halt_and_scope_repair_needed(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths)

    assert summary["micro_v2_closed_loss_scope_decision_status"] == "MICRO_V2_CLOSED_LOSSES_LEGITIMATE_KEEP_DAILY_HALT"
    assert summary["closed_loss_legitimate"] is True
    assert summary["closed_trade_count"] == 2
    assert summary["closed_scaled_pnl_total"] == -9.996
    assert summary["quarantined_contamination_detected"] is False
    assert summary["pnl_integrity_status"] == "PNL_INTEGRITY_OK"
    assert summary["daily_risk_scope_status"] == "DAILY_RISK_SCOPE_MISMATCH_REPAIR_NEEDED"
    assert summary["next_allowed_action"] == "KEEP_DAILY_HALT_AND_PREPARE_LEDGER_SCOPE_REPAIR_PHASE"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_pnl_integrity_issue_blocks_scope_decision(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, scaled=-4.998, raw=-4.998, multiplier=0.5)
    summary = _run(paths)

    assert summary["micro_v2_closed_loss_scope_decision_status"] == "MICRO_V2_CLOSED_LOSSES_PNL_INTEGRITY_ISSUE"
    assert summary["pnl_integrity_status"] == "PNL_INTEGRITY_ISSUE"


def test_quarantined_trade_contamination_blocks_scope_decision(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, quarantined_pnl=-1.0)
    summary = _run(paths)

    assert summary["micro_v2_closed_loss_scope_decision_status"] == "MICRO_V2_CLOSED_LOSSES_QUARANTINE_CONTAMINATION"
    assert summary["quarantined_contamination_detected"] is True


def test_scope_mismatch_metadata_only_without_closed_loss() -> None:
    scope = audit_daily_risk_scope(
        {"daily_risk_clearances": [{"canonical_cleared_for_profile": "BALANCED_STABLE_MICRO"}]},
        closed_scaled_pnl_total=0.0,
    )

    assert scope["daily_risk_scope_status"] == "DAILY_RISK_SCOPE_MISMATCH_METADATA_ONLY"


def test_scope_valid_wait_for_reset_with_v2_ledger(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, ledger_profile="BALANCED_STABLE_MICRO_V2")
    summary = _run(paths)

    assert summary["micro_v2_closed_loss_scope_decision_status"] == "MICRO_V2_DAILY_RISK_SCOPE_VALID_WAIT_FOR_RESET"
    assert summary["daily_risk_scope_status"] == "DAILY_RISK_SCOPE_VALID"


def test_safety_flags_block_decision(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, execution_attempted=True)
    summary = _run(paths)

    assert summary["micro_v2_closed_loss_scope_decision_status"] == "MICRO_V2_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_cli_mode_exists_and_generates_reports(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    code = main(
        [
            "--mode",
            "micro-v2-closed-loss-scope-decision",
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
            "--drawdown-recovery-dir",
            str(paths["drawdown_dir"]),
            "--open-trade-repair-dir",
            str(paths["open_repair_dir"]),
            "--schema-repair-dir",
            str(paths["schema_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert code == 0
    assert (paths["out"] / "micro_v2_closed_loss_scope_decision_summary.json").exists()


def test_no_sqlite_or_ledger_mutation(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    sqlite_before = paths["v2_sqlite"].read_bytes()
    ledger_before = paths["daily_ledger"].read_text(encoding="utf-8")
    _run(paths)

    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert paths["daily_ledger"].read_text(encoding="utf-8") == ledger_before


def test_no_order_send_order_check_and_config_safety() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_closed_loss_scope_decision(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        daily_risk_ledger=paths["daily_ledger"],
        drawdown_recovery_dir=paths["drawdown_dir"],
        open_trade_repair_dir=paths["open_repair_dir"],
        schema_repair_dir=paths["schema_dir"],
        output_dir=paths["out"],
    )


def _fixture(
    tmp_path: Path,
    *,
    scaled: float = -4.998,
    raw: float = -49.98,
    multiplier: float = 0.1,
    quarantined_pnl: float = 0.0,
    ledger_profile: str = "BALANCED_STABLE_MICRO",
    execution_attempted: bool = False,
) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "daily_ledger": tmp_path / "data" / "reports" / "paper_daily_risk" / "paper_daily_risk_ledger.json",
        "drawdown_dir": tmp_path / "data" / "reports" / "micro_v2_daily_drawdown_state_recovery_after_open_trade_repair",
        "open_repair_dir": tmp_path / "data" / "reports" / "micro_v2_guarded_open_trade_integrity_repair",
        "schema_dir": tmp_path / "data" / "reports" / "micro_v2_papertrade_schema_repair",
        "out": tmp_path / "data" / "reports" / "micro_v2_closed_loss_scope_decision",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _insert_closed(paths["v2_sqlite"], "ptr_closed_1", raw=raw, scaled=scaled, multiplier=multiplier)
    _insert_closed(paths["v2_sqlite"], "ptr_closed_2", raw=raw, scaled=scaled, multiplier=multiplier)
    _insert_quarantined(paths["v2_sqlite"], "ptr_quarantined", pnl=quarantined_pnl)
    _insert_halt(paths["v2_sqlite"])
    if execution_attempted:
        _insert_heartbeat(paths["v2_sqlite"], execution_attempted=True)
    paths["profile"].write_text(
        "PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\n",
        encoding="utf-8",
    )
    paths["daily_ledger"].write_text(
        json.dumps({"daily_risk_clearances": [{"daily_risk_clearance_id": "dr1", "created_at_utc": "2026-06-01T00:00:00+00:00", "canonical_cleared_for_profile": ledger_profile}]}),
        encoding="utf-8",
    )
    (paths["drawdown_dir"] / "micro_v2_daily_drawdown_state_recovery_summary.json").write_text(json.dumps({"drawdown_halt_root_cause": "LEGITIMATE_CLOSED_PAPER_LOSS_DRAWDOWN"}), encoding="utf-8")
    (paths["open_repair_dir"] / "micro_v2_guarded_open_trade_integrity_repair_summary.json").write_text(json.dumps({"open_trade_count_after": 0}), encoding="utf-8")
    (paths["schema_dir"] / "micro_v2_papertrade_schema_repair_summary.json").write_text(json.dumps({"schema_status": "OK"}), encoding="utf-8")
    return paths


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT UNIQUE, signal_id TEXT, idempotency_key TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT, updated_at_utc TEXT)")
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)")
        conn.commit()
    finally:
        conn.close()


def _insert_closed(path: Path, trade_id: str, *, raw: float, scaled: float, multiplier: float) -> None:
    payload = {
        "paper_trade_id": trade_id,
        "symbol": "USDJPY",
        "direction": "SELL",
        "entry_time_utc": "2026-06-01T01:00:00+00:00",
        "exit_time_utc": "2026-06-01T02:00:00+00:00",
        "entry_price": 159.40,
        "exit_price": 159.50,
        "sl_price": 159.60,
        "tp_price": 159.10,
        "status": "CLOSED",
        "exit_reason": "STOP_LOSS",
        "raw_pnl": raw,
        "scaled_paper_pnl": scaled,
        "paper_risk_multiplier": multiplier,
    }
    _insert_trade(path, trade_id, "CLOSED", payload, closed_at="2026-06-01T02:00:00+00:00")


def _insert_quarantined(path: Path, trade_id: str, *, pnl: float) -> None:
    payload = {
        "paper_trade_id": trade_id,
        "symbol": "USDJPY",
        "entry_price": 159.40,
        "sl_price": 159.40,
        "tp_price": 159.50,
        "status": "QUARANTINED_INVALID_OPEN_TRADE",
        "scaled_paper_pnl": pnl,
    }
    _insert_trade(path, trade_id, "QUARANTINED_INVALID_OPEN_TRADE", payload, closed_at=None)


def _insert_trade(path: Path, trade_id: str, status: str, payload: dict[str, object], *, closed_at: str | None) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, signal_id, idempotency_key, symbol, status, payload_json, opened_at_utc, closed_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade_id, f"sig_{trade_id}", f"paper_trade:{trade_id}", payload.get("symbol"), status, json.dumps(payload), payload.get("entry_time_utc", ""), closed_at, closed_at or payload.get("entry_time_utc", "")),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_halt(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        payload = {"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT", "execution_attempted": False, "order_send_called": False, "order_check_called": False}
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("PAPER_SHADOW_HALTED", "USDJPY", "2026-06-01T02:05:00+00:00", "WARNING", "PAPER_DAILY_DRAWDOWN_HALT", json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_heartbeat(path: Path, *, execution_attempted: bool) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb1", "2026-06-01T02:10:00+00:00", "forward-shadow", 1, int(execution_attempted), json.dumps({"execution_attempted": execution_attempted})),
        )
        conn.commit()
    finally:
        conn.close()
