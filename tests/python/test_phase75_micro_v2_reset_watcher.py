from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5.cli import main
from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_reset_watcher import run_micro_v2_reset_watcher


def test_reset_watcher_keeps_waiting_while_daily_halt_active(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=True, daily_reset_occurred=False, relaunch_allowed=False)
    summary = _run(paths)
    assert summary["micro_v2_reset_watcher_status"] == "MICRO_V2_RESET_WATCHER_KEEP_WAITING"
    assert summary["post_reset_relaunch_allowed"] is False
    assert summary["relaunch_command_available"] is False
    assert summary["recommended_next_action"] == "KEEP_V2_STOPPED_AND_RERUN_RESET_WATCHER_LATER"


def test_reset_watcher_ready_generates_manual_relaunch_command_pack(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True)
    summary = _run(paths)
    assert summary["micro_v2_reset_watcher_status"] == "MICRO_V2_RESET_WATCHER_READY_FOR_MANUAL_RELAUNCH"
    assert summary["post_reset_relaunch_allowed"] is True
    assert summary["relaunch_command_available"] is True
    commands = (paths["out"] / "recommended_commands.md").read_text(encoding="utf-8")
    assert "--mode forward-shadow" in commands
    assert "--mode status" in commands
    assert "--mode micro-v2-observation-checkpoint" in commands


def test_reset_watcher_scope_invalid_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, scope_ok=False)
    summary = _run(paths)
    assert summary["micro_v2_reset_watcher_status"] == "MICRO_V2_RESET_WATCHER_SCOPE_INVALID"
    assert summary["relaunch_command_available"] is False


def test_reset_watcher_zero_risk_guard_missing_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, guard_ok=False)
    summary = _run(paths)
    assert summary["micro_v2_reset_watcher_status"] == "MICRO_V2_RESET_WATCHER_ZERO_RISK_GUARD_MISSING"
    assert summary["relaunch_command_available"] is False


def test_reset_watcher_paper_state_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, paper_clean=False)
    summary = _run(paths)
    assert summary["micro_v2_reset_watcher_status"] == "MICRO_V2_RESET_WATCHER_PAPER_STATE_BLOCK"
    assert summary["relaunch_command_available"] is False


def test_reset_watcher_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, execution_attempted=True)
    summary = _run(paths)
    assert summary["micro_v2_reset_watcher_status"] == "MICRO_V2_RESET_WATCHER_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_reset_watcher_watch_mode_never_runs_forward_shadow(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=True, daily_reset_occurred=False, relaunch_allowed=False)
    summary = _run(paths, watch=True, interval_seconds=0, max_checks=2)
    assert summary["micro_v2_reset_watcher_status"] == "MICRO_V2_RESET_WATCHER_KEEP_WAITING"
    assert summary["checks_completed"] == 2
    assert summary["forward_shadow_executed"] is False
    assert summary["execution_attempted"] is False


def test_reset_watcher_cli_and_read_only_inputs(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=True, daily_reset_occurred=False, relaunch_allowed=False)
    sqlite_before = paths["v2_sqlite"].read_bytes()
    ledger_before = paths["daily_ledger"].read_text(encoding="utf-8")
    code = main(
        [
            "--mode",
            "micro-v2-reset-watcher",
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
            "--post-reset-relaunch-dir",
            str(paths["post_dir"]),
            "--pre-relaunch-safety-dir",
            str(paths["pre_dir"]),
            "--daily-risk-scope-repair-dir",
            str(paths["scope_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )
    assert code == 0
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert paths["daily_ledger"].read_text(encoding="utf-8") == ledger_before
    assert (paths["out"] / "micro_v2_reset_watcher_summary.json").exists()
    assert (paths["out"] / "reset_gate_recheck.json").exists()
    assert (paths["out"] / "relaunch_notification.json").exists()
    assert (paths["out"] / "report.html").exists()


def test_reset_watcher_preserves_global_safety_config() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False


def _run(
    paths: dict[str, Path],
    *,
    watch: bool = False,
    interval_seconds: int = 300,
    max_checks: int = 12,
) -> dict[str, object]:
    return run_micro_v2_reset_watcher(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        daily_risk_ledger=paths["daily_ledger"],
        post_reset_relaunch_dir=paths["post_dir"],
        pre_relaunch_safety_dir=paths["pre_dir"],
        daily_risk_scope_repair_dir=paths["scope_dir"],
        output_dir=paths["out"],
        watch=watch,
        interval_seconds=interval_seconds,
        max_checks=max_checks,
    )


def _fixture(
    tmp_path: Path,
    *,
    daily_halt_active: bool,
    daily_reset_occurred: bool,
    relaunch_allowed: bool,
    scope_ok: bool = True,
    guard_ok: bool = True,
    paper_clean: bool = True,
    execution_attempted: bool = False,
) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "daily_ledger": tmp_path / "data" / "reports" / "paper_daily_risk" / "paper_daily_risk_ledger.json",
        "post_dir": tmp_path / "data" / "reports" / "micro_v2_post_reset_relaunch_pack",
        "pre_dir": tmp_path / "data" / "reports" / "micro_v2_pre_relaunch_safety_pack",
        "scope_dir": tmp_path / "data" / "reports" / "micro_v2_daily_risk_scope_repair",
        "out": tmp_path / "data" / "reports" / "micro_v2_reset_watcher",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    paths["v2_sqlite"].write_bytes(b"sqlite-placeholder")
    paths["profile"].write_text(
        "PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\nNOT_FOR_LIVE=true\n",
        encoding="utf-8",
    )
    paths["daily_ledger"].write_text(json.dumps({"daily_risk_clearances": []}), encoding="utf-8")
    scope_status = "DAILY_RISK_SCOPE_OK_FOR_V2" if scope_ok else "DAILY_RISK_SCOPE_INVALID"
    _write_json(
        paths["post_dir"] / "micro_v2_post_reset_relaunch_pack_summary.json",
        {
            "daily_halt_active": daily_halt_active,
            "daily_reset_occurred": daily_reset_occurred,
            "post_reset_relaunch_allowed": relaunch_allowed,
            "daily_risk_scope_verified": scope_ok,
            "daily_risk_scope_status": scope_status,
            "zero_risk_guard_verified": guard_ok,
            "paper_state_clean_for_relaunch": paper_clean,
            "execution_attempted": execution_attempted,
            "order_send_called": False,
            "order_check_called": False,
        },
    )
    _write_json(
        paths["pre_dir"] / "micro_v2_pre_relaunch_safety_pack_summary.json",
        {
            "zero_risk_guard_enabled": guard_ok,
            "invalid_paper_trade_prevention_active": guard_ok,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        },
    )
    _write_json(
        paths["scope_dir"] / "micro_v2_daily_risk_scope_repair_summary.json",
        {
            "daily_risk_scope_status_after": scope_status,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        },
    )
    return paths


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
