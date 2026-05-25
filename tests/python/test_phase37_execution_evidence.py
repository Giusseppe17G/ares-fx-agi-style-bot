from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5.execution_evidence import run_execution_evidence_audit
from agi_style_forex_bot_mt5.execution_evidence.order_call_scanner import scan_order_call_evidence, summarize_findings
from agi_style_forex_bot_mt5.forward_evidence.operational_acceptance_gate import decide_operational_acceptance
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def _records(payload: dict[str, object], *, source: str = "events") -> list[dict[str, object]]:
    return [{"source_type": "test", "source": source, "row": "1", "payload": payload, "timestamp_utc": "2026-05-24T00:00:00+00:00"}]


def test_order_send_called_false_does_not_block() -> None:
    summary = summarize_findings(scan_order_call_evidence(_records({"order_send_called": False})))
    assert summary["execution_evidence_status"] == "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"
    assert summary["real_order_send_detected"] is False
    assert summary["blocking_findings"] == []


def test_order_check_called_false_and_execution_attempted_false_do_not_block() -> None:
    summary = summarize_findings(scan_order_call_evidence(_records({"order_check_called": False, "execution_attempted": False})))
    assert summary["execution_evidence_status"] == "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"
    assert summary["real_order_check_detected"] is False
    assert summary["execution_attempted_detected"] is False


def test_order_send_called_true_blocks() -> None:
    summary = summarize_findings(scan_order_call_evidence(_records({"order_send_called": True})))
    assert summary["execution_evidence_status"] == "EXECUTION_EVIDENCE_BLOCKED_REAL_ATTEMPT"
    assert summary["real_order_send_detected"] is True


def test_execution_attempted_true_blocks() -> None:
    summary = summarize_findings(scan_order_call_evidence(_records({"execution_attempted": True})))
    assert summary["execution_evidence_status"] == "EXECUTION_EVIDENCE_BLOCKED_REAL_ATTEMPT"
    assert summary["execution_attempted_detected"] is True


def test_text_mentions_that_were_not_called_do_not_block() -> None:
    summary = summarize_findings(scan_order_call_evidence(_records({"message": "order_send was not called and order_check was not called"})))
    assert summary["execution_evidence_status"] == "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"
    assert summary["blocking_findings"] == []


def test_doc_or_command_reference_does_not_block() -> None:
    summary = summarize_findings(scan_order_call_evidence(_records({"command": "py -m bot --mode forward-evidence # order_send prohibited"}, source="docs/OPERATIONAL_RUNBOOK.md")))
    assert summary["execution_evidence_status"] == "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"


def test_unknown_ambiguous_string_blocks_for_review() -> None:
    summary = summarize_findings(scan_order_call_evidence(_records({"message": "order_send result returned retcode"})))
    assert summary["execution_evidence_status"] == "EXECUTION_EVIDENCE_UNKNOWN_REVIEW_REQUIRED"
    assert summary["unknown_requires_review"] == 1


def test_forward_acceptance_no_longer_blocks_false_positive_false_fields() -> None:
    acceptance = decide_operational_acceptance(
        evidence={
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
            "stable_gate_confirmed": True,
            "heartbeat_count": 1,
            "hours_observed": 1,
            "invalid_timestamp_count": 0,
        },
        metrics={"closed_trades": 0, "paper_drawdown_status": "OK"},
        drift={"classification": "INSUFFICIENT_FORWARD_DATA"},
        paper_audit={"status": "OK"},
        execution_evidence={"execution_evidence_status": "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"},
    )
    assert acceptance["decision"] == "NEEDS_MORE_FORWARD_DATA"
    assert acceptance["execution_attempted"] is False


def test_execution_evidence_audit_generates_reports(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    reports = tmp_path / "reports"
    log_dir.mkdir()
    (reports / "forward_evidence").mkdir(parents=True)
    (log_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "TEST", "order_send_called": False, "order_check_called": False, "execution_attempted": False}) + "\n",
        encoding="utf-8",
    )
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    db.close()

    summary = run_execution_evidence_audit(sqlite_path=tmp_path / "forward.sqlite3", log_dir=log_dir, reports_root=reports, output_dir=tmp_path / "out")

    assert summary["execution_evidence_status"] == "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False
    assert (tmp_path / "out" / "execution_evidence_summary.json").exists()
    assert (tmp_path / "out" / "findings.csv").exists()
    assert (tmp_path / "out" / "false_positive_mentions.csv").exists()
    assert (tmp_path / "out" / "blocking_findings.csv").exists()
    assert (tmp_path / "out" / "report.html").exists()


def test_legacy_forward_evidence_true_without_primary_support_is_reviewed(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    reports = tmp_path / "reports"
    log_dir.mkdir()
    forward_evidence = reports / "forward_evidence"
    forward_evidence.mkdir(parents=True)
    (log_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "HEARTBEAT", "order_send_called": False, "order_check_called": False, "execution_attempted": False}) + "\n",
        encoding="utf-8",
    )
    (forward_evidence / "evidence_summary.json").write_text(
        json.dumps({"mode": "forward-evidence", "order_send_called": True, "order_check_called": True, "execution_attempted": False}),
        encoding="utf-8",
    )
    db = TelemetryDatabase(tmp_path / "forward.sqlite3")
    db.close()

    summary = run_execution_evidence_audit(sqlite_path=tmp_path / "forward.sqlite3", log_dir=log_dir, reports_root=reports, output_dir=tmp_path / "out")

    assert summary["execution_evidence_status"] == "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"
    assert summary["real_order_send_detected"] is False
    assert summary["real_order_check_detected"] is False
    assert summary["blocking_findings"] == []
