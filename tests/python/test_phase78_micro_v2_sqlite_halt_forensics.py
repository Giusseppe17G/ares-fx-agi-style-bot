from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agi_style_forex_bot_mt5.cli import main
from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_sqlite_halt_forensics import run_micro_v2_sqlite_halt_forensics


def test_forensics_detects_tables_columns_and_schema(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths)
    schema = json.loads((paths["out"] / "schema_inventory.json").read_text(encoding="utf-8"))
    table_names = {table["name"] for table in schema["tables"]}
    assert {"events", "alerts", "operational_state"}.issubset(table_names)
    assert summary["sqlite_table_count"] >= 3


def test_forensics_finds_sqlite_halt_events_and_detector_misses(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths)
    diagnostics = json.loads((paths["out"] / "halt_detector_diagnostics.json").read_text(encoding="utf-8"))
    assert summary["sqlite_halt_event_count"] >= 3
    assert summary["current_detector_miss_count"] >= 1
    assert "SOURCE_NOT_IN_CURRENT_EVENTS_DATASET" in diagnostics["miss_reasons"]


def test_forensics_compares_sqlite_and_jsonl(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths)
    comparison = json.loads((paths["out"] / "sqlite_vs_jsonl_comparison.json").read_text(encoding="utf-8"))
    assert summary["jsonl_halt_event_count"] >= 1
    assert comparison["sqlite_halt_event_count"] >= 1
    assert comparison["jsonl_halt_event_count"] >= 1


def test_forensics_detects_invalid_timestamps(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, invalid_timestamp=True)
    summary = _run(paths)
    assert summary["invalid_timestamp_count"] >= 1


def test_cli_mode_generates_reports_and_keeps_sqlite_read_only(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    before = paths["sqlite"].read_bytes()
    code = main(
        [
            "--mode",
            "micro-v2-sqlite-halt-forensics",
            "--sqlite",
            str(paths["sqlite"]),
            "--log-dir",
            str(paths["log_dir"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )
    assert code == 0
    assert paths["sqlite"].read_bytes() == before
    assert (paths["out"] / "sqlite_halt_forensics_summary.json").exists()
    assert (paths["out"] / "halt_events.csv").exists()
    assert (paths["out"] / "queries_used.sql").exists()


def test_forensics_reports_safety_flags_false(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary = _run(paths)
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_global_safety_defaults_intact() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return run_micro_v2_sqlite_halt_forensics(
        sqlite_path=paths["sqlite"],
        log_dir=paths["log_dir"],
        output_dir=paths["out"],
    )


def _fixture(tmp_path: Path, *, invalid_timestamp: bool = False) -> dict[str, Path]:
    paths = {
        "sqlite": tmp_path / "data" / "sqlite" / "forward-shadow-v2-dryrun.sqlite3",
        "log_dir": tmp_path / "data" / "logs" / "forward-shadow-v2-dryrun",
        "out": tmp_path / "data" / "reports" / "micro_v2_sqlite_halt_forensics",
    }
    for path in paths.values():
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    _write_sqlite(paths["sqlite"], invalid_timestamp=invalid_timestamp)
    _write_jsonl(paths["log_dir"])
    return paths


def _write_sqlite(path: Path, *, invalid_timestamp: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = "not-a-timestamp" if invalid_timestamp else "2026-06-05T00:00:00+00:00"
    with sqlite3.connect(path) as conn:
        conn.execute("create table events (id integer primary key, event_type text, timestamp_utc text, message text, payload_json text)")
        conn.execute("create table alerts (id integer primary key, alert_code text, severity text, timestamp_utc text, payload_json text)")
        conn.execute("create table operational_state (state_key text primary key, payload_json text, updated_at_utc text)")
        conn.execute(
            "insert into events(event_type, timestamp_utc, message, payload_json) values (?, ?, ?, ?)",
            ("PAPER_SHADOW_HALTED", "2026-06-05T00:00:01+00:00", "shadow halted", json.dumps({"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"})),
        )
        conn.execute(
            "insert into alerts(alert_code, severity, timestamp_utc, payload_json) values (?, ?, ?, ?)",
            ("PAPER_DAILY_DRAWDOWN", "CRITICAL", timestamp, json.dumps({"drawdown": -3.5})),
        )
        conn.execute(
            "insert into operational_state(state_key, payload_json, updated_at_utc) values (?, ?, ?)",
            (
                "runtime",
                json.dumps(
                    {
                        "shadow_paused": True,
                        "halt_reason": "PAPER_DAILY_DRAWDOWN_HALT",
                        "latest_exit_reason": "CONFIG_ERROR",
                        "execution_attempted": False,
                    }
                ),
                "2026-06-05T00:00:02+00:00",
            ),
        )


def _write_jsonl(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {"event_type": "PAPER_SHADOW_HALTED", "timestamp_utc": "2026-06-05T00:00:03+00:00", "payload": {"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT", "execution_attempted": False}},
        {"event_type": "HEARTBEAT", "timestamp_utc": "2026-06-05T00:00:04+00:00", "payload": {"execution_attempted": False}},
    ]
    (log_dir / "events-2026-06-05.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
