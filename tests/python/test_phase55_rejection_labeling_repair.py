from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor import run_micro_v2_dry_run_monitor
from agi_style_forex_bot_mt5.micro_v2_symbol_rejection_audit import run_micro_v2_symbol_rejection_audit
from agi_style_forex_bot_mt5.rejection_labeling import classify_rejection_event_type, run_rejection_labeling_audit


def test_stale_tick_is_not_labeled_symbol_rejected() -> None:
    event_type = classify_rejection_event_type(payload={"tick_time_status": "STALE", "normalization_reason": "tick timestamp is stale"})
    assert event_type == "STALE_TICK_REJECTION"


def test_market_closed_is_not_labeled_symbol_rejected() -> None:
    event_type = classify_rejection_event_type(reject_code="MARKET_CLOSED_OR_NO_TICKS", payload={"market_is_probably_closed": True})
    assert event_type == "MARKET_CLOSED_REJECTION"


def test_true_symbol_rejection_stays_symbol_rejected() -> None:
    event_type = classify_rejection_event_type(reject_code="SYMBOL_NOT_FOUND", reject_reason="symbol not found", payload={"symbol": "EURUSD"})
    assert event_type == "SYMBOL_REJECTED"


def test_audit_parses_legacy_misclassified_events(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_event(paths["v2_sqlite"], "SYMBOL_REJECTED", "EURUSD", {"tick_time_status": "STALE", "normalization_reason": "tick timestamp is stale"})

    summary = _run_labeling(paths)

    assert summary["rejection_labeling_status"] == "REJECTION_LABELING_LEGACY_MISCLASSIFICATIONS_ONLY"
    assert summary["suspected_misclassified_symbol_rejections"] == 1
    assert summary["stale_tick_rejection_count"] == 0


def test_monitor_v2_shows_stale_tick_separately(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _insert_heartbeat(paths["v2_sqlite"])
    _insert_event(paths["v2_sqlite"], "STALE_TICK_REJECTION", "EURUSD", {"reject_reason": "tick timestamp is stale"})

    summary = run_micro_v2_dry_run_monitor(
        base_sqlite=paths["base_sqlite"],
        base_log_dir=paths["base_log_dir"],
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        output_dir=paths["out"],
    )

    assert summary["v2_signals_rejected"] == 1
    activity = json.loads((paths["out"] / "v2_activity_summary.json").read_text(encoding="utf-8"))
    assert activity["rejected_by_reason"][0]["rejection_reason"] == "tick timestamp is stale"


def test_phase54_auditor_detects_legacy_misclassified(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _write_profile(paths["profile"])
    paths["stable_gate"].parent.mkdir(parents=True, exist_ok=True)
    paths["stable_gate"].write_text(json.dumps({"classification": "PAPER_SHADOW_READY"}), encoding="utf-8")
    _insert_event(paths["v2_sqlite"], "SYMBOL_REJECTED", "EURUSD", {"tick_time_status": "STALE", "normalization_reason": "tick timestamp is stale"})

    summary = run_micro_v2_symbol_rejection_audit(
        v2_sqlite=paths["v2_sqlite"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        v2_profile_config=paths["profile"],
        stable_gate=paths["stable_gate"],
        monitor_dir=paths["monitor_dir"],
        output_dir=paths["symbol_out"],
    )

    assert summary["micro_v2_symbol_rejection_status"] == "SYMBOL_REJECTION_ROOT_CAUSE_FOUND"
    assert summary["symbol_rejection_root_cause"] == "STALE_TICK_OR_MARKET_CLOSED_REJECTION_RECORDED_AS_SYMBOL_REJECTED"


def test_cli_rejection_labeling_audit_does_not_modify_sqlite(tmp_path: Path, capsys) -> None:
    paths = _fixture(tmp_path)
    _insert_event(paths["v2_sqlite"], "STALE_TICK_REJECTION", "EURUSD", {"reject_reason": "tick timestamp is stale"})
    before = paths["v2_sqlite"].read_bytes()

    result = cli.main(
        [
            "--mode",
            "rejection-labeling-audit",
            "--base-sqlite",
            str(paths["base_sqlite"]),
            "--v2-sqlite",
            str(paths["v2_sqlite"]),
            "--base-log-dir",
            str(paths["base_log_dir"]),
            "--v2-log-dir",
            str(paths["v2_log_dir"]),
            "--reports-root",
            str(paths["reports_root"]),
            "--output-dir",
            str(paths["label_out"]),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["rejection_labeling_status"] == "REJECTION_LABELING_FIXED"
    assert summary["stale_tick_rejection_count"] == 1
    assert paths["v2_sqlite"].read_bytes() == before
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False
    assert summary["execution_attempted"] is False


def _run_labeling(paths: dict[str, Path]) -> dict[str, object]:
    return run_rejection_labeling_audit(
        base_sqlite=paths["base_sqlite"],
        v2_sqlite=paths["v2_sqlite"],
        base_log_dir=paths["base_log_dir"],
        v2_log_dir=paths["v2_log_dir"],
        reports_root=paths["reports_root"],
        output_dir=paths["label_out"],
    )


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "base_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-stable.sqlite3",
        "v2_sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "base_log_dir": tmp_path / "data" / "logs" / "forward-shadow-stable",
        "v2_log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "reports_root": tmp_path / "data" / "reports",
        "out": tmp_path / "data" / "reports" / "micro_v2_dry_run_monitor",
        "label_out": tmp_path / "data" / "reports" / "rejection_labeling_audit",
        "symbol_out": tmp_path / "data" / "reports" / "micro_v2_symbol_rejection_audit",
        "monitor_dir": tmp_path / "data" / "reports" / "micro_v2_dry_run_monitor",
        "profile": tmp_path / "data" / "reports" / "paper_risk" / "balanced_stable_micro_v2.ini",
        "stable_gate": tmp_path / "data" / "reports" / "stable_gate" / "stable_gate_summary.json",
    }
    for key in ("base_log_dir", "v2_log_dir", "reports_root", "monitor_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    _init_db(paths["base_sqlite"])
    _init_db(paths["v2_sqlite"])
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


def _insert_event(path: Path, event_type: str, symbol: str, payload: dict[str, object]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, symbol, datetime.now(timezone.utc).isoformat(), "WARNING", str(payload.get("reject_reason") or event_type.lower()), json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_heartbeat(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO heartbeats (heartbeat_id, timestamp_utc, mode, mt5_connected, execution_attempted, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("hb", datetime.now(timezone.utc).isoformat(), "forward-shadow", 1, 0, json.dumps({"execution_attempted": False})),
        )
        conn.commit()
    finally:
        conn.close()


def _write_profile(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("PROFILE_NAME=BALANCED_STABLE_MICRO_V2\nPAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\n", encoding="utf-8")
