from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_symbol_rejection_audit import run_micro_v2_symbol_rejection_audit


def test_detects_cli_symbol_parse_bug(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_symbol_rejected(paths["v2_sqlite"], "EURUSD,GBPUSD,USDJPY", {"symbol": "EURUSD,GBPUSD,USDJPY", "reason": "symbol_rejected"})

    summary = _run(paths)

    assert summary["micro_v2_symbol_rejection_status"] == "SYMBOL_REJECTION_DUE_TO_CLI_SYMBOL_PARSE"
    assert summary["execution_attempted"] is False


def test_detects_type_mismatch_stringified_list(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, profile_extra={"ALLOWED_SYMBOLS": "[EURUSD,GBPUSD]"})
    _insert_symbol_rejected(paths["v2_sqlite"], "EURUSD", {"symbol": "EURUSD", "reason": "symbol_rejected"})

    summary = _run(paths)

    assert summary["micro_v2_symbol_rejection_status"] == "SYMBOL_REJECTION_DUE_TO_TYPE_MISMATCH"
    assert summary["fix_candidate_created"] is True


def test_detects_profile_universe_mismatch(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, profile_extra={"ALLOWED_SYMBOLS": "GBPUSD"})
    _insert_symbol_rejected(paths["v2_sqlite"], "EURUSD", {"symbol": "EURUSD", "reason": "symbol_rejected"})

    summary = _run(paths)

    assert summary["micro_v2_symbol_rejection_status"] == "SYMBOL_REJECTION_DUE_TO_PROFILE_UNIVERSE"
    assert (paths["out"] / "symbol_rejection_fix_plan.md").exists()
    assert (paths["out"] / "balanced_stable_micro_v2_symbol_fix_candidate.ini").exists()


def test_detects_stable_gate_universe_mismatch(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, stable_gate={"allowed_symbols": ["GBPUSD"], "classification": "PAPER_SHADOW_READY"})
    _insert_symbol_rejected(paths["v2_sqlite"], "EURUSD", {"symbol": "EURUSD", "reason": "symbol_rejected"})

    summary = _run(paths)

    assert summary["micro_v2_symbol_rejection_status"] == "SYMBOL_REJECTION_DUE_TO_STABLE_GATE_UNIVERSE"


def test_detects_broker_suffix_mismatch(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_symbol_rejected(paths["v2_sqlite"], "EURUSD", {"symbol": "EURUSD", "canonical_symbol": "EURUSD", "broker_symbol": "EURUSD.r", "reason": "symbol_rejected"})

    summary = _run(paths)

    assert summary["micro_v2_symbol_rejection_status"] == "SYMBOL_REJECTION_DUE_TO_BROKER_SUFFIX"
    assert summary["fix_candidate_created"] is True


def test_stale_tick_root_cause_found_without_candidate(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_symbol_rejected(
        paths["v2_sqlite"],
        "EURUSD",
        {
            "symbol": "EURUSD",
            "canonical_symbol": "EURUSD",
            "broker_symbol": "EURUSD",
            "reason": "symbol_rejected",
            "tick_time_status": "STALE",
            "market_is_probably_closed": True,
            "normalization_reason": "tick timestamp is stale",
        },
    )

    summary = _run(paths)

    assert summary["micro_v2_symbol_rejection_status"] == "SYMBOL_REJECTION_ROOT_CAUSE_FOUND"
    assert summary["symbol_rejection_root_cause"] == "STALE_TICK_OR_MARKET_CLOSED_REJECTION_RECORDED_AS_SYMBOL_REJECTED"
    assert summary["fix_candidate_created"] is False


def test_cli_generates_reports_and_does_not_modify_inputs(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path, profile_extra={"ALLOWED_SYMBOLS": "GBPUSD"})
    _insert_symbol_rejected(paths["v2_sqlite"], "EURUSD", {"symbol": "EURUSD", "reason": "symbol_rejected"})
    sqlite_before = paths["v2_sqlite"].read_bytes()
    profile_before = paths["profile"].read_bytes()

    result = cli.main(
        [
            "--mode",
            "micro-v2-symbol-rejection-audit",
            "--v2-sqlite",
            str(paths["v2_sqlite"]),
            "--v2-log-dir",
            str(paths["v2_log_dir"]),
            "--reports-root",
            str(paths["reports_root"]),
            "--v2-profile-config",
            str(paths["profile"]),
            "--stable-gate",
            str(paths["stable_gate"]),
            "--monitor-dir",
            str(paths["monitor_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["micro_v2_symbol_rejection_status"] == "SYMBOL_REJECTION_DUE_TO_PROFILE_UNIVERSE"
    assert paths["v2_sqlite"].read_bytes() == sqlite_before
    assert paths["profile"].read_bytes() == profile_before
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False
    assert summary["execution_attempted"] is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_symbol_rejection_audit(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        stable_gate=paths["stable_gate"],
        monitor_dir=paths["monitor_dir"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path, *, profile_extra: dict[str, str] | None = None, stable_gate: dict[str, object] | None = None) -> dict[str, Path]:
    paths = {
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "stable_gate": tmp_path / "data" / "reports" / "stable_gate" / "stable_gate_summary.json",
        "monitor_dir": tmp_path / "data" / "reports" / "micro_v2_dry_run_monitor",
        "out": tmp_path / "data" / "reports" / "micro_v2_symbol_rejection_audit",
    }
    paths["v2_log_dir"].mkdir(parents=True, exist_ok=True)
    paths["monitor_dir"].mkdir(parents=True, exist_ok=True)
    _init_db(paths["v2_sqlite"])
    _write_profile(paths["profile"], profile_extra or {})
    paths["stable_gate"].parent.mkdir(parents=True, exist_ok=True)
    paths["stable_gate"].write_text(json.dumps(stable_gate or {"classification": "PAPER_SHADOW_READY"}), encoding="utf-8")
    (paths["monitor_dir"] / "micro_v2_dry_run_monitor_summary.json").write_text(json.dumps({"v2_signals_detected": 1}), encoding="utf-8")
    return paths


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, symbol TEXT, timestamp_utc TEXT, severity TEXT, message TEXT, payload_json TEXT)"
        )
        conn.execute(
            "CREATE TABLE heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, heartbeat_id TEXT, timestamp_utc TEXT, mode TEXT, mt5_connected INTEGER, execution_attempted INTEGER, payload_json TEXT)"
        )
        conn.execute(
            "CREATE TABLE paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, paper_trade_id TEXT, symbol TEXT, status TEXT, payload_json TEXT, opened_at_utc TEXT, closed_at_utc TEXT)"
        )
        conn.commit()
    finally:
        conn.close()


def _insert_symbol_rejected(path: Path, symbol: str, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("SYMBOL_REJECTED", symbol, datetime.now(timezone.utc).isoformat(), "WARNING", "symbol_rejected", json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _write_profile(path: Path, extra: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "PROFILE_NAME": "BALANCED_STABLE_MICRO_V2",
        "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO_V2",
        "PAPER_ONLY": "true",
        "NOT_FOR_DEMO_LIVE": "true",
        "NOT_FOR_LIVE": "true",
        "APPROVED_FOR_PAPER_DRY_RUN_ONLY": "true",
        "APPROVED_FOR_DEMO": "false",
        "APPROVED_FOR_LIVE": "false",
    }
    values.update(extra)
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
