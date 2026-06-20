from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agi_style_forex_bot_mt5.cli import main
from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_post_reset_relaunch import run_micro_v2_post_reset_relaunch


def test_reset_not_occurred_waits(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_reset=False, daily_halt=True)
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_WAITING_RESET"
    assert summary["relaunch_allowed"] is False


def test_cooldown_active_waits(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, cooldown_active=True)
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_WAITING_COOLDOWN"
    assert summary["relaunch_allowed"] is False


def test_config_error_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, latest_exit_reason="CONFIG_ERROR")
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_BLOCKED"
    assert "no_active_config_error" in summary["blocking_gate_ids"]


def test_mt5_disconnected_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, mt5_connected=False)
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_BLOCKED"
    assert "mt5_diagnostics_pass" in summary["blocking_gate_ids"]


def test_stale_clearance_blocks(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, clearance_ok=False)
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_BLOCKED"
    assert "clearance_not_stale" in summary["blocking_gate_ids"]


def test_relaunch_ready_when_all_gates_clean(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_status="MICRO_V2_WAITING_FOR_MARKET_OPEN")
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_READY"
    assert summary["relaunch_allowed"] is True
    commands = (paths["out"] / "relaunch_commands.ps1").read_text(encoding="utf-8")
    assert "# py -m agi_style_forex_bot_mt5.cli --mode forward-shadow" in commands


def test_safe_to_observe_when_ticks_fresh(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, market_status="MICRO_V2_MARKET_OPEN_TICKS_FRESH")
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_SAFE_TO_OBSERVE"
    assert summary["safe_to_observe"] is True


def test_drawdown_active_blocks_by_reset_gate(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, daily_reset=False, daily_halt=True)
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_WAITING_RESET"
    assert "daily_reset_real" in summary["blocking_gate_ids"]


def test_corrupted_evidence_waits_for_manual_review(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    (paths["reports_root"] / "execution_evidence" / "execution_evidence_summary.json").write_text("{not json", encoding="utf-8")
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_WAITING_MANUAL_REVIEW"
    assert "evidence_integrity_acceptable" in summary["blocking_gate_ids"]


def test_rejected_symbols_block(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, symbol_rejection_status="SYMBOL_REJECTION_DUE_TO_PROFILE_UNIVERSE")
    summary = _run(paths)
    assert summary["micro_v2_relaunch_decision"] == "MICRO_V2_RELAUNCH_BLOCKED"
    assert "symbols_available" in summary["blocking_gate_ids"]


def test_cli_generates_reports_and_keeps_sqlite_read_only(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    sqlite_before = paths["v2_sqlite"].read_bytes()
    code = main(
        [
            "--mode",
            "micro-v2-post-reset-relaunch",
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
            "--output-dir",
            str(paths["out"]),
        ]
    )
    assert code == 0
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert (paths["out"] / "relaunch_summary.json").exists()
    assert (paths["out"] / "relaunch_decision.json").exists()
    assert (paths["out"] / "relaunch_gates.json").exists()
    assert (paths["out"] / "relaunch_commands.ps1").exists()


def test_no_order_send_order_check_and_config_safety() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_post_reset_relaunch(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        daily_risk_ledger=paths["daily_ledger"],
        post_reset_relaunch_dir=paths["post_dir"],
        output_dir=paths["out"],
    )


def _fixture(
    tmp_path: Path,
    *,
    daily_reset: bool = True,
    daily_halt: bool = False,
    cooldown_active: bool = False,
    latest_exit_reason: str = "",
    halt_reason: str = "",
    block_new_entries: bool = False,
    mt5_connected: bool = True,
    clearance_ok: bool = True,
    market_status: str = "MICRO_V2_WAITING_FOR_MARKET_OPEN",
    symbol_rejection_status: str = "SYMBOL_REJECTION_ROOT_CAUSE_FOUND",
) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "daily_ledger": tmp_path / "data" / "reports" / "paper_daily_risk" / "paper_daily_risk_ledger.json",
        "post_dir": tmp_path / "data" / "reports" / "micro_v2_post_reset_relaunch_pack",
        "out": tmp_path / "data" / "reports" / "micro_v2_post_reset_relaunch",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _write_sqlite(paths["v2_sqlite"], latest_exit_reason=latest_exit_reason, halt_reason=halt_reason, block_new_entries=block_new_entries, mt5_connected=mt5_connected)
    paths["profile"].write_text(
        "\n".join(
            [
                "PROFILE_NAME=BALANCED_STABLE_MICRO_V2",
                "PAPER_ONLY=true",
                "NOT_FOR_DEMO_LIVE=true",
                "NOT_FOR_LIVE=true",
                "APPROVED_FOR_PAPER_DRY_RUN_ONLY=true",
                "APPROVED_FOR_DEMO=false",
                "APPROVED_FOR_LIVE=false",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(paths["daily_ledger"], {"daily_risk_clearances": []})
    reports = paths["reports_root"]
    _write_json(
        reports / "micro_v2_reset_watcher" / "micro_v2_reset_watcher_summary.json",
        {
            "daily_halt_active": daily_halt,
            "daily_reset_occurred": daily_reset,
            "post_reset_relaunch_allowed": daily_reset and not daily_halt,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        },
    )
    _write_json(
        paths["post_dir"] / "micro_v2_post_reset_relaunch_pack_summary.json",
        {
            "daily_halt_active": daily_halt,
            "daily_reset_occurred": daily_reset,
            "daily_risk_scope_verified": True,
            "daily_risk_scope_status": "DAILY_RISK_SCOPE_OK_FOR_V2",
            "paper_state_clean_for_relaunch": halt_reason != "PAPER_STATE_ERROR",
            "post_reset_relaunch_allowed": daily_reset and not daily_halt,
            "open_trade_count": 0,
            "invalid_open_trade_count": 0,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        },
    )
    _write_json(reports / "micro_v2_pre_relaunch_safety_pack" / "micro_v2_pre_relaunch_safety_pack_summary.json", {"zero_risk_guard_enabled": True, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(reports / "micro_v2_daily_risk_scope_repair" / "micro_v2_daily_risk_scope_repair_summary.json", {"daily_risk_scope_status_after": "DAILY_RISK_SCOPE_OK_FOR_V2", "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(
        reports / "micro_v2_clearance_runtime_check" / "micro_v2_clearance_runtime_check_summary.json",
        {
            "micro_v2_clearance_runtime_check_status": "MICRO_V2_CLEARANCE_RUNTIME_MATCH_OK" if clearance_ok else "MICRO_V2_CLEARANCE_RUNTIME_MATCH_FAILED",
            "clearance_profile_match": clearance_ok,
            "daily_risk_accepted": clearance_ok,
            "approved_for_demo": False,
            "approved_for_live": False,
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        },
    )
    _write_json(reports / "paper_risk" / "paper_risk_status.json", {"cooldown_active": cooldown_active, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(
        reports / "micro_v2_market_open_readiness" / "micro_v2_market_open_readiness_summary.json",
        {"micro_v2_market_open_readiness_status": market_status, "mt5_connected": mt5_connected, "execution_attempted": False, "order_send_called": False, "order_check_called": False},
    )
    _write_json(reports / "telemetry_repair" / "telemetry_status_summary.json", {"telemetry_acceptance_clear": True, "active_blocking_count": 0, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(reports / "execution_evidence" / "execution_evidence_summary.json", {"blocking_findings_count": 0, "execution_attempted_detected": False, "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(reports / "rejection_labeling_audit" / "rejection_labeling_summary.json", {"rejection_labeling_status": "REJECTION_LABELING_FIXED", "execution_attempted": False, "order_send_called": False, "order_check_called": False})
    _write_json(
        reports / "micro_v2_symbol_rejection_audit" / "micro_v2_symbol_rejection_summary.json",
        {"micro_v2_symbol_rejection_status": symbol_rejection_status, "symbol_rejection_root_cause": "STALE_TICK_OR_MARKET_CLOSED_REJECTION_RECORDED_AS_SYMBOL_REJECTED" if symbol_rejection_status == "SYMBOL_REJECTION_ROOT_CAUSE_FOUND" else "", "execution_attempted": False, "order_send_called": False, "order_check_called": False},
    )
    return paths


def _write_sqlite(path: Path, *, latest_exit_reason: str, halt_reason: str, block_new_entries: bool, mt5_connected: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute("create table paper_trades (id integer primary key, status text, payload_json text)")
        con.execute("create table heartbeats (id integer primary key, timestamp_utc text, mt5_connected integer, execution_attempted integer, payload_json text)")
        con.execute("create table operational_state (state_key text primary key, payload_json text, updated_at_utc text)")
        con.execute("insert into heartbeats(timestamp_utc, mt5_connected, execution_attempted, payload_json) values ('2026-06-05T00:00:00+00:00', ?, 0, '{}')", (1 if mt5_connected else 0,))
        con.execute(
            "insert into operational_state(state_key, payload_json, updated_at_utc) values ('runtime', ?, '2026-06-05T00:00:00+00:00')",
            (json.dumps({"latest_exit_reason": latest_exit_reason, "halt_reason": halt_reason, "block_new_entries": block_new_entries, "execution_attempted": False}),),
        )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
