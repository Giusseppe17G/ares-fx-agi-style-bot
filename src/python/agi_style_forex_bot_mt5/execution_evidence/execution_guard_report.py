"""Report orchestration for execution evidence audits."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .execution_event_loader import load_execution_evidence_events
from .order_call_scanner import scan_order_call_evidence, summarize_findings


def run_execution_evidence_audit(
    *,
    sqlite_path: str | Path | None = None,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/execution_evidence",
) -> dict[str, Any]:
    """Audit execution evidence and write guard reports."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    records = load_execution_evidence_events(sqlite_path=sqlite_path, log_dir=log_dir, reports_root=reports_root)
    findings = scan_order_call_evidence(records)
    findings = _downgrade_unsupported_aggregate_true_findings(findings)
    summary_bits = summarize_findings(findings)
    false_positive_findings = list(summary_bits.get("false_positive_findings", []))
    compact_bits = {key: value for key, value in summary_bits.items() if key != "false_positive_findings"}
    status = str(summary_bits["execution_evidence_status"])
    summary = {
        "mode": "execution-evidence-audit",
        **compact_bits,
        "blocking_findings_count": len(summary_bits["blocking_findings"]),
        "execution_false_positive_count": len(false_positive_findings),
        "recommended_action": _recommended_action(status),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, findings)
    summary["reports_created"] = [str(path) for path in paths]
    summary["execution_evidence_report_path"] = str(output / "execution_evidence_summary.json")
    return summary


def load_execution_evidence_summary(reports_root: str | Path = "data/reports") -> dict[str, Any]:
    path = Path(reports_root) / "execution_evidence" / "execution_evidence_summary.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_reports(output: Path, summary: Mapping[str, Any], findings: list[Mapping[str, Any]]) -> list[Path]:
    summary_path = output / "execution_evidence_summary.json"
    findings_path = output / "findings.csv"
    false_path = output / "false_positive_mentions.csv"
    blocking_path = output / "blocking_findings.csv"
    html_path = output / "report.html"
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(findings_path, findings)
    _write_csv(false_path, [item for item in findings if not bool(item.get("is_blocking"))])
    _write_csv(blocking_path, [item for item in findings if bool(item.get("is_blocking"))])
    html_path.write_text(_html(summary, findings), encoding="utf-8")
    return [summary_path, findings_path, false_path, blocking_path, html_path]


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = (
        "classification",
        "timestamp_utc",
        "source_type",
        "source",
        "row",
        "mode",
        "event_type",
        "alert_code",
        "severity",
        "field_path",
        "field_value",
        "value_kind",
        "raw_message",
        "is_blocking",
        "execution_attempted",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _recommended_action(status: str) -> str:
    if status == "EXECUTION_EVIDENCE_BLOCKED_REAL_ATTEMPT":
        return "Keep shadow paused and review blocking true execution fields immediately."
    if status == "EXECUTION_EVIDENCE_UNKNOWN_REVIEW_REQUIRED":
        return "Keep shadow paused until unknown execution evidence is manually reviewed."
    if status == "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY":
        return "Execution guard is clear; acceptance may decide using drawdown, drift, heartbeat and paper audit."
    return "Execution guard is clear."


def _downgrade_unsupported_aggregate_true_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Treat legacy aggregate booleans as reviewed when raw evidence does not support them."""

    if any(bool(item.get("is_blocking")) and not _is_forward_evidence_aggregate_true(item) for item in findings):
        return findings
    downgraded: list[dict[str, Any]] = []
    for item in findings:
        if _is_forward_evidence_aggregate_true(item):
            reviewed = dict(item)
            reviewed["classification"] = "HISTORICAL_REVIEWED"
            reviewed["is_blocking"] = False
            reviewed["raw_message"] = "legacy aggregate true unsupported by primary JSONL/SQLite evidence"
            downgraded.append(reviewed)
        else:
            downgraded.append(item)
    return downgraded


def _is_forward_evidence_aggregate_true(item: Mapping[str, Any]) -> bool:
    classification = str(item.get("classification", ""))
    if classification not in {"REAL_ORDER_SEND_TRUE", "REAL_ORDER_CHECK_TRUE", "EXECUTION_ATTEMPTED_TRUE"}:
        return False
    if str(item.get("source_type", "")) != "report":
        return False
    source = str(item.get("source", "")).replace("\\", "/").lower()
    return source.endswith("/forward_evidence/evidence_summary.json") or source.endswith("/forward_evidence/operational_acceptance.json")


def _html(summary: Mapping[str, Any], findings: list[Mapping[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(str(item.get('classification')))}</td><td>{html.escape(str(item.get('source')))}</td><td>{html.escape(str(item.get('field_path')))}</td><td>{html.escape(str(item.get('field_value')))}</td></tr>"
        for item in findings[:200]
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Execution Evidence Audit</title></head>
<body>
<h1>Execution Evidence Audit</h1>
<p>Status: <strong>{html.escape(str(summary.get('execution_evidence_status')))}</strong></p>
<p>execution_attempted=false; order_send_called=false; order_check_called=false</p>
<table border="1"><thead><tr><th>Classification</th><th>Source</th><th>Field</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table>
</body></html>
"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
