"""Report orchestration for telemetry timestamp audit and quarantine."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .evidence_window_filter import telemetry_acceptance_window_summary
from .telemetry_quarantine_ledger import load_quarantine_ledger, quarantine_historical_issues
from .timestamp_issue_classifier import classify_timestamp_issue, summarize_classified_issues
from .timestamp_issue_loader import load_timestamp_issues


def run_telemetry_timestamp_audit(
    *,
    sqlite_path: str | Path | None = None,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/telemetry_repair",
) -> dict[str, Any]:
    """Audit timestamp issues and write repair reports without mutating source evidence."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    raw_issues, context = load_timestamp_issues(sqlite_path=sqlite_path, log_dir=log_dir, reports_root=reports_root)
    ledger = load_quarantine_ledger(output)
    issues = [classify_timestamp_issue(issue, context, ledger) for issue in raw_issues]
    summary_bits = summarize_classified_issues(issues, ledger)
    summary = {
        "mode": "telemetry-timestamp-audit",
        **{key: value for key, value in summary_bits.items() if key not in {"active_blocking_issues", "historical_issues", "quarantined_issues", "unknown_issues"}},
        **telemetry_acceptance_window_summary(context, summary_bits),
        "recommended_action": _recommended_action(summary_bits),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, issues, summary_bits)
    summary["reports_created"] = [str(path) for path in paths]
    summary["telemetry_report_path"] = str(output / "telemetry_timestamp_summary.json")
    return summary


def run_quarantine_telemetry_issues(
    *,
    sqlite_path: str | Path | None = None,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/telemetry_repair",
    reason: str = "Historical telemetry reviewed",
    issue_class: str = "",
    status: str = "QUARANTINED",
) -> dict[str, Any]:
    """Quarantine historical timestamp issues in a ledger only."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    raw_issues, context = load_timestamp_issues(sqlite_path=sqlite_path, log_dir=log_dir, reports_root=reports_root)
    ledger = load_quarantine_ledger(output)
    issues = [classify_timestamp_issue(issue, context, ledger) for issue in raw_issues]
    result = quarantine_historical_issues(issues=issues, output_dir=output, reason=reason, status=status, issue_class=issue_class)
    refreshed = run_telemetry_timestamp_audit(sqlite_path=sqlite_path, log_dir=log_dir, reports_root=reports_root, output_dir=output)
    return {
        "mode": "quarantine-telemetry-issues",
        **result,
        "telemetry_status": refreshed.get("telemetry_status"),
        "telemetry_acceptance_clear": refreshed.get("telemetry_acceptance_clear"),
        "active_blocking_count": refreshed.get("active_blocking_count", 0),
        "quarantined_count": refreshed.get("quarantined_count", 0),
        "recommended_action": refreshed.get("recommended_action", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def run_telemetry_status(
    *,
    sqlite_path: str | Path | None = None,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/telemetry_repair",
) -> dict[str, Any]:
    """Return compact telemetry status, refreshing the audit report."""

    summary = run_telemetry_timestamp_audit(sqlite_path=sqlite_path, log_dir=log_dir, reports_root=reports_root, output_dir=output_dir)
    return {
        "mode": "telemetry-status",
        "telemetry_status": summary.get("telemetry_status"),
        "active_blocking_count": summary.get("active_blocking_count", 0),
        "historical_invalid_count": summary.get("historical_invalid_count", 0),
        "historical_quarantined_count": summary.get("quarantined_count", 0),
        "historical_reviewed_count": summary.get("reviewed_count", 0),
        "historical_unreviewed_count": summary.get("historical_unreviewed_count", summary.get("unquarantined_historical_count", 0)),
        "telemetry_acceptance_clear": summary.get("telemetry_acceptance_clear", False),
        "telemetry_policy_reason": summary.get("telemetry_policy_reason", ""),
        "latest_clean_window_start_utc": summary.get("latest_clean_window_start_utc", ""),
        "recommended_action": summary.get("recommended_action", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def run_telemetry_acceptance_policy(
    *,
    sqlite_path: str | Path | None = None,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/telemetry_repair",
) -> dict[str, Any]:
    """Return the compact telemetry policy decision used by forward acceptance."""

    summary = run_telemetry_timestamp_audit(sqlite_path=sqlite_path, log_dir=log_dir, reports_root=reports_root, output_dir=output_dir)
    return {
        "mode": "telemetry-acceptance-policy",
        "telemetry_status": summary.get("telemetry_status"),
        "telemetry_acceptance_clear": summary.get("telemetry_acceptance_clear", False),
        "telemetry_policy_reason": summary.get("telemetry_policy_reason", ""),
        "active_blocking_count": summary.get("active_blocking_count", 0),
        "historical_invalid_count": summary.get("historical_invalid_count", 0),
        "quarantined_count": summary.get("quarantined_count", 0),
        "reviewed_count": summary.get("reviewed_count", 0),
        "unreviewed_count": summary.get("historical_unreviewed_count", summary.get("unquarantined_historical_count", 0)),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def load_telemetry_timestamp_summary(reports_root: str | Path = "data/reports") -> dict[str, Any]:
    path = Path(reports_root) / "telemetry_repair" / "telemetry_timestamp_summary.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_reports(output: Path, summary: Mapping[str, Any], issues: list[Mapping[str, Any]], summary_bits: Mapping[str, Any]) -> list[Path]:
    summary_path = output / "telemetry_timestamp_summary.json"
    issues_path = output / "timestamp_issues.csv"
    active_path = output / "active_blocking_issues.csv"
    historical_path = output / "historical_issues.csv"
    html_path = output / "report.html"
    summary_path.write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(issues_path, issues)
    _write_csv(active_path, list(summary_bits.get("active_blocking_issues", [])))
    _write_csv(historical_path, list(summary_bits.get("historical_issues", [])))
    html_path.write_text(_html(summary, issues), encoding="utf-8")
    return [summary_path, issues_path, active_path, historical_path, html_path]


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = (
        "issue_id",
        "classification",
        "field_name",
        "raw_value",
        "source",
        "source_type",
        "row",
        "event_type",
        "first_seen_utc",
        "severity",
        "warning",
        "affects_metrics",
        "affects_acceptance",
        "ledger_status",
        "suggested_action",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _recommended_action(summary: Mapping[str, Any]) -> str:
    if int(summary.get("active_blocking_count", 0) or 0) > 0:
        return "Keep acceptance blocked; repair active timestamp producer before resuming paper/shadow."
    if int(summary.get("unquarantined_historical_count", 0) or 0) > 0:
        return "Run quarantine-telemetry-issues after reviewing historical corrupt timestamps; do not delete original evidence."
    if int(summary.get("quarantined_count", 0) or 0) > 0:
        return "Telemetry guard is clear for quarantined historical issues; rerun forward-acceptance."
    return "Telemetry guard is clear."


def _html(summary: Mapping[str, Any], issues: list[Mapping[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(str(item.get('classification')))}</td><td>{html.escape(str(item.get('source')))}</td><td>{html.escape(str(item.get('field_name')))}</td><td>{html.escape(str(item.get('raw_value')))}</td></tr>"
        for item in issues[:200]
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Telemetry Timestamp Audit</title></head>
<body>
<h1>Telemetry Timestamp Audit</h1>
<p>Status: <strong>{html.escape(str(summary.get('telemetry_status')))}</strong></p>
<p>execution_attempted=false; order_send_called=false; order_check_called=false</p>
<table border="1"><thead><tr><th>Classification</th><th>Source</th><th>Field</th><th>Raw Value</th></tr></thead><tbody>{rows}</tbody></table>
</body></html>
"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
