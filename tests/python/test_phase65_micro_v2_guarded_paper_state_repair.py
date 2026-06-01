from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_guarded_paper_state_repair import run_micro_v2_guarded_paper_state_repair


TRADE_ID = "ptr_feeb8b599ded418587a211c8c3235dbb"


def test_dry_run_does_not_modify_sqlite(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    before = paths["v2_sqlite"].read_bytes()
    summary = _run(paths, apply=False)
    assert summary["micro_v2_guarded_repair_status"] == "MICRO_V2_REPAIR_DRY_RUN_READY"
    assert summary["repair_applied"] is False
    assert paths["v2_sqlite"].read_bytes() == before


def test_apply_creates_backup(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths, apply=True)
    assert summary["micro_v2_guarded_repair_status"] == "MICRO_V2_REPAIR_APPLIED_SUCCESSFULLY"
    assert summary["backup_created"] is True
    assert Path(str(summary["backup_path"])).exists()


def test_runtime_active_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, heartbeat_recent=True)
    summary = _run(paths, apply=True)
    assert summary["micro_v2_guarded_repair_status"] == "MICRO_V2_REPAIR_BLOCKED_RUNTIME_ACTIVE"


def test_plan_mismatch_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, root_cause="TP_EQUALS_ENTRY")
    summary = _run(paths, apply=True)
    assert summary["micro_v2_guarded_repair_status"] == "MICRO_V2_REPAIR_BLOCKED_PLAN_MISMATCH"


def test_trade_not_found_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, insert_trade=False)
    summary = _run(paths, apply=True)
    assert summary["micro_v2_guarded_repair_status"] == "MICRO_V2_REPAIR_BLOCKED_TRADE_NOT_FOUND"


def test_trade_already_closed_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, trade_status="CLOSED")
    summary = _run(paths, apply=True)
    assert summary["micro_v2_guarded_repair_status"] == "MICRO_V2_REPAIR_BLOCKED_TRADE_ALREADY_CLOSED"


def test_unsafe_action_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, action="RECONSTRUCT_SL_TP_FROM_VALID_SIGNAL_CONTEXT")
    summary = _run(paths, apply=True)
    assert summary["micro_v2_guarded_repair_status"] == "MICRO_V2_REPAIR_BLOCKED_UNSAFE_ACTION"


def test_quarantine_success_no_closed_trade_or_pnl(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    before = _counts(paths["v2_sqlite"])
    summary = _run(paths, apply=True)
    after = _counts(paths["v2_sqlite"])
    assert summary["quarantined_trade_count"] == 1
    assert after["closed"] == before["closed"]
    assert after["realized_pnl"] == before["realized_pnl"]
    assert after["invalid_open"] == 0
    row = _trade_row(paths["v2_sqlite"])
    payload = json.loads(row["payload_json"])
    assert row["closed_at_utc"] in {"", None}
    assert "realized_pnl" not in payload


def test_safety_flags_true_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, safety=True)
    summary = _run(paths, apply=True)
    assert summary["micro_v2_guarded_repair_status"] == "MICRO_V2_REPAIR_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False


def test_cli_no_profile_or_stable_modification(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path)
    stable_before = paths["stable_sqlite"].read_bytes()
    profile_before = paths["profile"].read_text(encoding="utf-8")
    result = cli.main(
        [
            "--mode",
            "micro-v2-guarded-paper-state-repair",
            "--v2-sqlite",
            str(paths["v2_sqlite"]),
            "--v2-log-dir",
            str(paths["v2_log_dir"]),
            "--repair-plan",
            str(paths["repair_plan"]),
            "--forensics-dir",
            str(paths["forensics_dir"]),
            "--lifecycle-dir",
            str(paths["lifecycle_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )
    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["execution_attempted"] is False
    assert paths["stable_sqlite"].read_bytes() == stable_before
    assert paths["profile"].read_text(encoding="utf-8") == profile_before


def _run(paths: dict[str, Path], *, apply: bool) -> dict[str, object]:
    return run_micro_v2_guarded_paper_state_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        repair_plan=paths["repair_plan"],
        forensics_dir=paths["forensics_dir"],
        lifecycle_dir=paths["lifecycle_dir"],
        output_dir=paths["out"],
        backup_root=paths["backup_root"],
        apply_repair=apply,
    )


def _fixture(
    tmp_path: Path,
    *,
    insert_trade: bool = True,
    trade_status: str = "OPEN",
    action: str = "QUARANTINE_INVALID_PAPER_TRADE",
    root_cause: str = "SL_EQUALS_ENTRY",
    heartbeat_recent: bool = False,
    safety: bool = False,
) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "stable_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "repair_plan": tmp_path / "data" / "reports" / "micro_v2_invalid_trade_forensics" / "repair_plan.json",
        "forensics_dir": tmp_path / "data" / "reports" / "micro_v2_invalid_trade_forensics",
        "lifecycle_dir": tmp_path / "data" / "reports" / "micro_v2_lifecycle_risk_comparison",
        "out": tmp_path / "data" / "reports" / "micro_v2_guarded_paper_state_repair",
        "backup_root": tmp_path / "data" / "backups" / "micro_v2_guarded_paper_state_repair",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _init_db(paths["stable_sqlite"])
    if insert_trade:
        _insert_trade(paths["v2_sqlite"], status=trade_status)
    _heartbeat(paths["v2_sqlite"], recent=heartbeat_recent, safety=safety)
    paths["profile"].write_text("PAPER_ONLY=true\n", encoding="utf-8")
    _write_json(
        paths["repair_plan"],
        {
            "repair_action_recommended": action,
            "target_trade_ids": [TRADE_ID],
            "root_cause": root_cause,
            "NOT_APPLIED": True,
            "PAPER_ONLY": True,
            "REQUIRES_BACKUP": True,
            "REQUIRES_RUNTIME_STOP": True,
            "REQUIRES_EXPLICIT_NEXT_PHASE": True,
            "APPROVED_FOR_RUNTIME": False,
            "APPROVED_FOR_DEMO": False,
            "APPROVED_FOR_LIVE": False,
        },
    )
    _write_json(paths["forensics_dir"] / "micro_v2_invalid_trade_forensics_summary.json", {"repair_action_recommended": action, "affected_symbols": ["EURUSD"]})
    _write_json(paths["lifecycle_dir"] / "micro_v2_lifecycle_risk_comparison_summary.json", {"micro_v2_lifecycle_risk_comparison_status": "MICRO_V2_OPEN_TRADES_INVALID_RISK_DISTANCE"})
    (paths["v2_log_dir"] / "events.jsonl").write_text('{"event_type":"HEARTBEAT","execution_attempted":false}\n', encoding="utf-8")
    return paths


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, signal_id TEXT, idempotency_key TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT, updated_at_utc TEXT)")
        conn.execute("CREATE TABLE paper_trade_events (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, event_type TEXT, timestamp_utc TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)")
        conn.commit()
    finally:
        conn.close()


def _insert_trade(path: Path, *, status: str) -> None:
    payload = {
        "paper_trade_id": TRADE_ID,
        "symbol": "EURUSD",
        "entry_price": 1.16542,
        "sl_price": 1.16542,
        "tp_price": 1.16363,
        "side": "SELL",
        "status": status,
    }
    conn = sqlite3.connect(path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO paper_trades (paper_trade_id, signal_id, idempotency_key, symbol, status, payload_json, opened_at_utc, closed_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (TRADE_ID, "sig", "idem", "EURUSD", status, json.dumps(payload), now, "" if status == "OPEN" else now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _heartbeat(path: Path, *, recent: bool, safety: bool) -> None:
    ts = datetime.now(timezone.utc) - timedelta(seconds=10 if recent else 600)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", ts.isoformat(), "forward-shadow", 1, int(safety), json.dumps({"execution_attempted": safety})),
        )
        conn.commit()
    finally:
        conn.close()


def _counts(path: Path) -> dict[str, object]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM paper_trades")]
    finally:
        conn.close()
    closed = [row for row in rows if str(row["status"]).upper() == "CLOSED"]
    invalid_open = [row for row in rows if str(row["status"]).upper() == "OPEN"]
    pnl = 0.0
    for row in closed:
        payload = json.loads(row["payload_json"])
        pnl += float(payload.get("realized_pnl", 0.0) or 0.0)
    return {"closed": len(closed), "invalid_open": len(invalid_open), "realized_pnl": pnl}


def _trade_row(path: Path) -> sqlite3.Row:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM paper_trades WHERE paper_trade_id = ?", (TRADE_ID,)).fetchone()
    finally:
        conn.close()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
