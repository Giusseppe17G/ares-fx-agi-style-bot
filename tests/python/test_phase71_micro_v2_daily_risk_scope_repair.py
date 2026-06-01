from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agi_style_forex_bot_mt5.cli import main
from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_daily_risk_scope_repair import run_micro_v2_daily_risk_scope_repair


def test_dry_run_detects_scope_mismatch_and_proposes_repair(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths)

    assert summary["micro_v2_daily_risk_scope_repair_status"] == "MICRO_V2_DAILY_RISK_SCOPE_DRY_RUN_READY"
    assert summary["daily_risk_scope_status_before"] == "DAILY_RISK_SCOPE_MISMATCH_REPAIR_NEEDED"
    assert summary["repair_applied"] is False
    assert summary["daily_halt_active"] is True
    assert summary["closed_scaled_pnl_total"] == -9.996


def test_apply_creates_backup_and_adds_v2_scope(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    before_ledger = _load(paths["daily_ledger"])
    summary = _run(paths, apply_repair=True, backup_root=paths["backup_root"])
    after_ledger = _load(paths["daily_ledger"])

    assert summary["micro_v2_daily_risk_scope_repair_status"] == "MICRO_V2_DAILY_RISK_SCOPE_REPAIR_APPLIED"
    assert summary["backup_created"] is True
    assert Path(str(summary["backup_path"])).exists()
    assert summary["daily_risk_scope_status_after"] == "DAILY_RISK_SCOPE_OK_FOR_V2"
    assert summary["daily_halt_active"] is True
    assert summary["closed_scaled_pnl_total"] == -9.996
    assert summary["closed_trade_count"] == 2
    assert len(after_ledger["daily_risk_clearances"]) == len(before_ledger["daily_risk_clearances"]) + 1
    assert after_ledger["daily_risk_clearances"][0]["canonical_cleared_for_profile"] == "BALANCED_STABLE_MICRO"
    assert after_ledger["daily_risk_clearances"][-1]["canonical_cleared_for_profile"] == "BALANCED_STABLE_MICRO_V2"
    assert after_ledger["daily_risk_clearances"][-1]["active_halts_cleared"] is False
    assert after_ledger["daily_risk_clearances"][-1]["closed_scaled_pnl_total"] == -9.996


def test_no_repair_needed_when_v2_scope_exists(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, include_v2=True)
    summary = _run(paths)

    assert summary["micro_v2_daily_risk_scope_repair_status"] == "MICRO_V2_DAILY_RISK_SCOPE_NO_REPAIR_NEEDED"
    assert summary["daily_risk_scope_status_before"] == "DAILY_RISK_SCOPE_OK_FOR_V2"


def test_unsafe_reset_blocks_repair(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, include_v2=True, v2_active_halts_cleared=True)
    summary = _run(paths, apply_repair=True, backup_root=paths["backup_root"])

    assert summary["micro_v2_daily_risk_scope_repair_status"] == "MICRO_V2_DAILY_RISK_SCOPE_BLOCKED_UNSAFE_RESET"
    assert summary["repair_applied"] is False


def test_pnl_mismatch_blocks_repair(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, closed_scaled_pnl=-8.0)
    summary = _run(paths, apply_repair=True, backup_root=paths["backup_root"])

    assert summary["micro_v2_daily_risk_scope_repair_status"] == "MICRO_V2_DAILY_RISK_SCOPE_BLOCKED_PNL_MISMATCH"
    assert summary["repair_applied"] is False


def test_backup_failed_blocks_apply(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    bad_backup_root = tmp_path / "data" / "backups" / "not_a_directory"
    bad_backup_root.parent.mkdir(parents=True, exist_ok=True)
    bad_backup_root.write_text("not a directory", encoding="utf-8")
    summary = _run(paths, apply_repair=True, backup_root=bad_backup_root)

    assert summary["micro_v2_daily_risk_scope_repair_status"] == "MICRO_V2_DAILY_RISK_SCOPE_BLOCKED_BACKUP_FAILED"
    assert summary["repair_applied"] is False


def test_no_sqlite_or_profile_mutation(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    sqlite_before = paths["v2_sqlite"].read_bytes()
    profile_before = paths["profile"].read_text(encoding="utf-8")
    _run(paths, apply_repair=True, backup_root=paths["backup_root"])

    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert paths["profile"].read_text(encoding="utf-8") == profile_before


def test_cli_mode_exists(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    code = main(
        [
            "--mode",
            "micro-v2-daily-risk-scope-repair",
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
            "--closed-loss-scope-dir",
            str(paths["closed_loss_dir"]),
            "--drawdown-recovery-dir",
            str(paths["drawdown_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert code == 0
    assert (paths["out"] / "micro_v2_daily_risk_scope_repair_summary.json").exists()


def test_no_order_send_order_check_and_config_safety() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False


def _run(paths: dict[str, Path], *, apply_repair: bool = False, backup_root: Path | None = None) -> dict[str, object]:
    return run_micro_v2_daily_risk_scope_repair(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        daily_risk_ledger=paths["daily_ledger"],
        closed_loss_scope_dir=paths["closed_loss_dir"],
        drawdown_recovery_dir=paths["drawdown_dir"],
        output_dir=paths["out"],
        backup_root=backup_root or paths["backup_root"],
        apply_repair=apply_repair,
    )


def _fixture(
    tmp_path: Path,
    *,
    include_v2: bool = False,
    v2_active_halts_cleared: bool = False,
    closed_scaled_pnl: float = -9.996,
) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "daily_ledger": tmp_path / "data" / "reports" / "paper_daily_risk" / "paper_daily_risk_ledger.json",
        "closed_loss_dir": tmp_path / "data" / "reports" / "micro_v2_closed_loss_scope_decision",
        "drawdown_dir": tmp_path / "data" / "reports" / "micro_v2_daily_drawdown_state_recovery_after_open_trade_repair",
        "out": tmp_path / "data" / "reports" / "micro_v2_daily_risk_scope_repair",
        "backup_root": tmp_path / "data" / "backups" / "micro_v2_daily_risk_scope_repair",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    entries = [_entry("BALANCED_STABLE_MICRO", active_halts_cleared=False, closed_scaled_pnl_total=None)]
    if include_v2:
        entries.append(_entry("BALANCED_STABLE_MICRO_V2", active_halts_cleared=v2_active_halts_cleared, closed_scaled_pnl_total=closed_scaled_pnl))
    paths["daily_ledger"].write_text(json.dumps({"mode": "paper-daily-risk-ledger", "daily_risk_clearances": entries, "execution_attempted": False}, indent=2), encoding="utf-8")
    (paths["closed_loss_dir"] / "micro_v2_closed_loss_scope_decision_summary.json").write_text(
        json.dumps(
            {
                "micro_v2_closed_loss_scope_decision_status": "MICRO_V2_CLOSED_LOSSES_LEGITIMATE_KEEP_DAILY_HALT",
                "closed_loss_legitimate": True,
                "closed_trade_count": 2,
                "closed_scaled_pnl_total": closed_scaled_pnl,
                "quarantined_trade_count": 3,
                "daily_halt_should_remain": True,
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        ),
        encoding="utf-8",
    )
    (paths["drawdown_dir"] / "micro_v2_daily_drawdown_state_recovery_summary.json").write_text(
        json.dumps({"micro_v2_daily_drawdown_state_recovery_status": "MICRO_V2_DRAWDOWN_HALT_LEGITIMATE", "closed_scaled_pnl_total": closed_scaled_pnl}),
        encoding="utf-8",
    )
    return paths


def _entry(profile: str, *, active_halts_cleared: bool, closed_scaled_pnl_total: float | None) -> dict[str, object]:
    entry: dict[str, object] = {
        "daily_risk_clearance_id": f"pdrc_{profile.lower()}",
        "canonical_cleared_for_profile": profile,
        "cleared_for_profile": profile,
        "created_at_utc": "2026-06-01T00:00:00+00:00",
        "active_halts_cleared": active_halts_cleared,
        "stale_halts_cleared": not active_halts_cleared,
        "daily_halt_active": not active_halts_cleared,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    if closed_scaled_pnl_total is not None:
        entry["closed_scaled_pnl_total"] = closed_scaled_pnl_total
        entry["closed_trade_count"] = 2
    return entry


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute("CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)")
        conn.execute("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT UNIQUE, symbol TEXT, status TEXT, payload_json TEXT)")
        conn.commit()
    finally:
        conn.close()


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
