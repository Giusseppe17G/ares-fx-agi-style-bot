from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5.cli import main
from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_post_reset_relaunch_pack import run_micro_v2_post_reset_relaunch_pack


def test_daily_halt_active_keep_halted(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=True, daily_reset_occurred=False, relaunch_allowed=False)
    summary = _run(paths)
    assert summary["micro_v2_post_reset_relaunch_pack_status"] == "MICRO_V2_POST_RESET_KEEP_HALTED_DAILY_HALT_ACTIVE"
    assert summary["post_reset_relaunch_allowed"] is False


def test_ready_for_relaunch_generates_commands(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True)
    summary = _run(paths)
    assert summary["micro_v2_post_reset_relaunch_pack_status"] == "MICRO_V2_POST_RESET_READY_FOR_RELAUNCH"
    assert summary["post_reset_relaunch_allowed"] is True
    commands = (paths["out"] / "recommended_commands.md").read_text(encoding="utf-8")
    assert "--mode forward-shadow" in commands
    assert "--mode micro-v2-observation-checkpoint" in commands


def test_scope_invalid_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, scope_ok=False)
    summary = _run(paths)
    assert summary["micro_v2_post_reset_relaunch_pack_status"] == "MICRO_V2_POST_RESET_SCOPE_INVALID"


def test_zero_risk_guard_missing_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, guard_ok=False)
    summary = _run(paths)
    assert summary["micro_v2_post_reset_relaunch_pack_status"] == "MICRO_V2_POST_RESET_ZERO_RISK_GUARD_MISSING"


def test_open_invalid_and_paper_state_blocks(tmp_path: Path) -> None:
    open_paths = _fixture(tmp_path / "open", daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, open_trades=1)
    invalid_paths = _fixture(tmp_path / "invalid", daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, invalid_trades=1)
    paper_paths = _fixture(tmp_path / "paper", daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, paper_clean=False)
    assert _run(open_paths)["micro_v2_post_reset_relaunch_pack_status"] == "MICRO_V2_POST_RESET_OPEN_TRADES_BLOCK"
    assert _run(invalid_paths)["micro_v2_post_reset_relaunch_pack_status"] == "MICRO_V2_POST_RESET_INVALID_TRADES_BLOCK"
    assert _run(paper_paths)["micro_v2_post_reset_relaunch_pack_status"] == "MICRO_V2_POST_RESET_PAPER_STATE_BLOCK"


def test_safety_flags_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=False, daily_reset_occurred=True, relaunch_allowed=True, execution_attempted=True)
    summary = _run(paths)
    assert summary["micro_v2_post_reset_relaunch_pack_status"] == "MICRO_V2_POST_RESET_SAFETY_BLOCKED"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_cli_and_no_mutation(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_halt_active=True, daily_reset_occurred=False, relaunch_allowed=False)
    sqlite_before = paths["v2_sqlite"].read_bytes()
    ledger_before = paths["daily_ledger"].read_text(encoding="utf-8")
    code = main(
        [
            "--mode",
            "micro-v2-post-reset-relaunch-pack",
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
            "--daily-reset-readiness-dir",
            str(paths["reset_dir"]),
            "--pre-relaunch-safety-dir",
            str(paths["pre_dir"]),
            "--daily-risk-scope-repair-dir",
            str(paths["scope_dir"]),
            "--closed-loss-scope-dir",
            str(paths["closed_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )
    assert code == 0
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert paths["daily_ledger"].read_text(encoding="utf-8") == ledger_before
    assert (paths["out"] / "micro_v2_post_reset_relaunch_pack_summary.json").exists()


def test_no_order_send_order_check_and_config_safety() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_post_reset_relaunch_pack(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        daily_risk_ledger=paths["daily_ledger"],
        daily_reset_readiness_dir=paths["reset_dir"],
        pre_relaunch_safety_dir=paths["pre_dir"],
        daily_risk_scope_repair_dir=paths["scope_dir"],
        closed_loss_scope_dir=paths["closed_dir"],
        output_dir=paths["out"],
    )


def _fixture(
    tmp_path: Path,
    *,
    daily_halt_active: bool,
    daily_reset_occurred: bool,
    relaunch_allowed: bool,
    scope_ok: bool = True,
    guard_ok: bool = True,
    open_trades: int = 0,
    invalid_trades: int = 0,
    paper_clean: bool = True,
    execution_attempted: bool = False,
) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "daily_ledger": tmp_path / "data" / "reports" / "paper_daily_risk" / "paper_daily_risk_ledger.json",
        "reset_dir": tmp_path / "data" / "reports" / "micro_v2_daily_reset_readiness",
        "pre_dir": tmp_path / "data" / "reports" / "micro_v2_pre_relaunch_safety_pack",
        "scope_dir": tmp_path / "data" / "reports" / "micro_v2_daily_risk_scope_repair",
        "closed_dir": tmp_path / "data" / "reports" / "micro_v2_closed_loss_scope_decision",
        "out": tmp_path / "data" / "reports" / "micro_v2_post_reset_relaunch_pack",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    paths["v2_sqlite"].write_bytes(b"sqlite-placeholder")
    paths["profile"].write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\n", encoding="utf-8")
    paths["daily_ledger"].write_text(json.dumps({"daily_risk_clearances": []}), encoding="utf-8")
    _write_json(
        paths["reset_dir"] / "micro_v2_daily_reset_readiness_summary.json",
        {
            "daily_halt_active": daily_halt_active,
            "daily_reset_occurred": daily_reset_occurred,
            "current_operational_day": "2026-06-02" if daily_reset_occurred else "2026-06-01",
            "latest_halt_operational_day": "2026-06-01",
            "daily_risk_scope_status": "DAILY_RISK_SCOPE_OK_FOR_V2" if scope_ok else "DAILY_RISK_SCOPE_INVALID",
            "open_trade_count": open_trades,
            "invalid_open_trade_count": invalid_trades,
            "quarantined_trade_count": 3,
            "paper_state_clean_for_relaunch": paper_clean,
            "relaunch_allowed": relaunch_allowed,
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
            "sl_tp_side_guard_enabled": guard_ok,
            "precision_rounding_guard_enabled": guard_ok,
            "paper_trade_creation_guard_status": "PAPER_TRADE_CREATION_GUARD_ENABLED" if guard_ok else "MISSING",
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        },
    )
    _write_json(
        paths["scope_dir"] / "micro_v2_daily_risk_scope_repair_summary.json",
        {
            "daily_risk_scope_status_after": "DAILY_RISK_SCOPE_OK_FOR_V2" if scope_ok else "DAILY_RISK_SCOPE_INVALID",
            "closed_scaled_pnl_total": -9.996,
            "closed_trade_count": 2,
            "daily_halt_active": True,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        },
    )
    _write_json(paths["closed_dir"] / "micro_v2_closed_loss_scope_decision_summary.json", {"closed_trade_count": 2, "closed_scaled_pnl_total": -9.996})
    return paths


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
