"""FASE 79 - halt detection repair.

Covers the three defects proven by the FASE 78 forensics output:
1. the forensics scanner counted ordinary rows (any non-empty exit reason) as halt events,
2. the daily halt audit picked the last halt in list order instead of the newest one,
3. the daily halt audit ignored halt tokens carried outside the payload mapping.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.micro_v2_daily_reset_readiness.daily_halt_status_audit import audit_daily_halt_status
from agi_style_forex_bot_mt5.micro_v2_sqlite_halt_forensics.detector_diagnostics import diagnose_current_detector
from agi_style_forex_bot_mt5.micro_v2_sqlite_halt_forensics.halt_event_scanner import scan_sqlite_halt_events

NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)


def _halt_event(timestamp: str, source: str = "sqlite:events") -> dict[str, object]:
    return {
        "source": source,
        "event_type": "PAPER_DAILY_DRAWDOWN_HALT",
        "timestamp_utc": timestamp,
        "message": "",
        "payload": {},
    }


def test_normal_rows_are_not_scanned_as_halt_events() -> None:
    payload = {
        "rows_by_table": {
            "paper_trades": [
                {"_rowid_": 1, "status": "CLOSED", "latest_exit_reason": "TAKE_PROFIT", "closed_at_utc": "2026-06-01T12:00:00+00:00"},
                {"_rowid_": 2, "status": "CLOSED", "latest_exit_reason": "STOP_LOSS", "closed_at_utc": "2026-06-01T12:30:00+00:00"},
            ],
            "heartbeats": [{"_rowid_": 3, "mode": "PAPER", "timestamp_utc": "2026-06-01T12:01:00+00:00"}],
        }
    }
    assert scan_sqlite_halt_events(payload) == []


def test_real_halt_rows_are_still_scanned_and_classified() -> None:
    payload = {
        "rows_by_table": {
            "events": [{"_rowid_": 1, "event_type": "PAPER_DAILY_DRAWDOWN_HALT", "timestamp_utc": "2026-06-01T13:00:00+00:00", "payload_json": "{}"}],
            "operational_state": [
                {"_rowid_": 2, "state_key": "runtime", "updated_at_utc": "2026-06-01T13:05:00+00:00", "payload_json": '{"shadow_paused": true, "halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"}'}
            ],
        }
    }
    events = scan_sqlite_halt_events(payload)
    assert len(events) == 2
    assert {event["halt_evidence_class"] for event in events} == {"HALT_TOKEN"}


def test_detector_diagnostics_separates_in_scope_and_out_of_scope_misses() -> None:
    payload = {
        "rows_by_table": {
            "events": [{"_rowid_": 1, "event_type": "PAPER_DAILY_DRAWDOWN_HALT", "timestamp_utc": "2026-06-01T13:00:00+00:00", "payload_json": "{}"}],
            "alerts": [{"_rowid_": 2, "alert_code": "PAPER_DAILY_DRAWDOWN", "timestamp_utc": "2026-06-01T13:10:00+00:00", "payload_json": "{}"}],
        }
    }
    diagnostics = diagnose_current_detector(scan_sqlite_halt_events(payload))
    assert diagnostics["current_detector_match_count"] == 1
    assert diagnostics["in_scope_detector_miss_count"] == 0
    assert diagnostics["out_of_scope_detector_miss_count"] == 1


def test_latest_halt_is_selected_by_timestamp_not_list_order() -> None:
    dataset = {"events": [_halt_event("2026-09-04T10:00:00+00:00"), _halt_event("2026-09-01T10:00:00+00:00", source="jsonl:events.jsonl:1")]}
    audit = audit_daily_halt_status(dataset, current_utc=NOW)
    assert audit["latest_halt_utc"] == "2026-09-04T10:00:00+00:00"
    assert audit["daily_halt_active"] is True
    assert audit["daily_reset_occurred"] is False


def test_expired_halt_still_reports_daily_reset() -> None:
    dataset = {"events": [_halt_event("2026-09-01T10:00:00+00:00"), _halt_event("2026-09-03T10:00:00+00:00")]}
    audit = audit_daily_halt_status(dataset, current_utc=NOW)
    assert audit["latest_halt_utc"] == "2026-09-03T10:00:00+00:00"
    assert audit["daily_halt_active"] is False
    assert audit["daily_reset_occurred"] is True


def test_halt_token_outside_payload_is_detected() -> None:
    dataset = {
        "events": [
            {"source": "sqlite:events", "event_type": "SHADOW_STATE", "timestamp_utc": "2026-09-04T09:00:00+00:00", "message": "", "halt_reason": "PAPER_DAILY_DRAWDOWN_HALT", "payload": {}},
            {"source": "jsonl:events.jsonl:2", "event_type": "PAPER_SHADOW_HALTED", "timestamp_utc": "2026-09-04T09:30:00+00:00", "message": "", "payload": {}},
        ]
    }
    audit = audit_daily_halt_status(dataset, current_utc=NOW)
    assert audit["daily_halt_event_count"] == 2
    assert audit["daily_halt_active"] is True


def test_non_halt_events_do_not_produce_a_halt() -> None:
    dataset = {"events": [{"source": "sqlite:events", "event_type": "HEARTBEAT", "timestamp_utc": "2026-09-04T09:00:00+00:00", "message": "ok", "payload": {"latest_exit_reason": "TAKE_PROFIT"}}]}
    audit = audit_daily_halt_status(dataset, current_utc=NOW)
    assert audit["daily_halt_event_count"] == 0
    assert audit["daily_halt_active"] is False
    assert audit["daily_reset_occurred"] is False


def test_reset_readiness_keeps_halt_when_newest_halt_is_not_last_in_row_order(tmp_path) -> None:
    """End-to-end guard: an active same-day halt must block relaunch even when an older
    halt row was written after it."""

    import json
    import sqlite3
    from datetime import timedelta

    from test_phase72_micro_v2_daily_reset_readiness import NOW as PHASE72_NOW, _fixture, _run

    paths = _fixture(tmp_path, halt_time=PHASE72_NOW, ledger_time=PHASE72_NOW - timedelta(days=1))
    conn = sqlite3.connect(paths["v2_sqlite"])
    try:
        conn.execute(
            "INSERT INTO events (event_type, symbol, timestamp_utc, severity, message, payload_json) VALUES (?,?,?,?,?,?)",
            (
                "PAPER_SHADOW_HALTED",
                "USDJPY",
                (PHASE72_NOW - timedelta(days=3)).isoformat(),
                "CRITICAL",
                "older halt written later",
                json.dumps({"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT", "execution_attempted": False}),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    summary = _run(paths)
    assert summary["micro_v2_daily_reset_readiness_status"] == "MICRO_V2_DAILY_RESET_NOT_READY_KEEP_HALTED"
    assert summary["daily_halt_active"] is True
    assert summary["relaunch_allowed"] is False
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_global_safety_defaults_intact() -> None:
    cfg = load_config(None)
    assert cfg.demo_only is True
    assert cfg.live_trading_approved is False
