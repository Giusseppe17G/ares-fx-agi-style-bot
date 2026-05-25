"""Classify timestamp issues for telemetry acceptance policy."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .telemetry_quarantine_ledger import raw_value_hash
from agi_style_forex_bot_mt5.utils.safe_datetime import detect_redacted_datetime, safe_parse_datetime


def classify_timestamp_issue(issue: Mapping[str, Any], context: Mapping[str, Any], ledger: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return issue with classification and acceptance impact."""

    classified = dict(issue)
    ledger_entry = _ledger_entry(issue, ledger or {})
    if ledger_entry and str(ledger_entry.get("status")) in {"QUARANTINED", "REVIEWED"}:
        classified.update({"classification": "QUARANTINED_HISTORICAL", "affects_acceptance": False, "ledger_status": ledger_entry.get("status")})
        return classified
    source = str(issue.get("source", "")).lower()
    raw = issue.get("raw_value", "")
    if _safe_ignorable_source(source):
        classified.update({"classification": "SAFE_IGNORABLE_TEXT", "affects_acceptance": False})
        return classified
    if _is_active(issue, context):
        classification = "ACTIVE_TELEMETRY_INVALID"
    elif detect_redacted_datetime(raw):
        classification = "REDACTED_TIMESTAMP"
    elif str(issue.get("warning", "")).startswith("DATETIME_FUTURE"):
        classification = "FUTURE_TIMESTAMP"
    elif str(issue.get("warning", "")) == "DATETIME_MISSING":
        classification = "EMPTY_TIMESTAMP"
    else:
        classification = "HISTORICAL_TELEMETRY_INVALID"
    if classification in {"REDACTED_TIMESTAMP", "FUTURE_TIMESTAMP", "EMPTY_TIMESTAMP"} and not _is_active(issue, context):
        acceptance = False if classification == "EMPTY_TIMESTAMP" and not bool(issue.get("affects_metrics")) else True
        classification = "HISTORICAL_TELEMETRY_INVALID" if not acceptance else classification
    classified.update(
        {
            "classification": classification,
            "affects_acceptance": classification in {"ACTIVE_TELEMETRY_INVALID", "UNKNOWN_TELEMETRY_REVIEW_REQUIRED", "REDACTED_TIMESTAMP", "FUTURE_TIMESTAMP"},
            "ledger_status": ledger_entry.get("status") if ledger_entry else "OPEN",
        }
    )
    return classified


def summarize_classified_issues(issues: list[Mapping[str, Any]], ledger: Mapping[str, Any] | None = None) -> dict[str, Any]:
    active = [item for item in issues if item.get("classification") == "ACTIVE_TELEMETRY_INVALID"]
    unknown = [item for item in issues if item.get("classification") == "UNKNOWN_TELEMETRY_REVIEW_REQUIRED"]
    quarantined = [item for item in issues if item.get("classification") == "QUARANTINED_HISTORICAL"]
    reviewed = [item for item in quarantined if str(item.get("ledger_status")) == "REVIEWED"]
    historical = [
        item
        for item in issues
        if item.get("classification") in {"HISTORICAL_TELEMETRY_INVALID", "REDACTED_TIMESTAMP", "FUTURE_TIMESTAMP", "EMPTY_TIMESTAMP"}
        and item.get("classification") != "ACTIVE_TELEMETRY_INVALID"
    ]
    unquarantined_historical = [item for item in historical if str(item.get("ledger_status")) not in {"QUARANTINED", "REVIEWED"}]
    historical_total = [*historical, *quarantined]
    historical_invalid_count = len(historical_total)
    quarantined_count = len([item for item in quarantined if str(item.get("ledger_status")) == "QUARANTINED"])
    reviewed_count = len(reviewed)
    unreviewed_count = len(unquarantined_historical)
    if active:
        status = "TELEMETRY_ACTIVE_BLOCKING"
    elif unknown:
        status = "TELEMETRY_UNKNOWN_REVIEW_REQUIRED"
    elif unquarantined_historical:
        status = "TELEMETRY_HISTORICAL_ISSUES_ONLY"
    elif quarantined:
        status = "TELEMETRY_HISTORICAL_QUARANTINED"
    else:
        status = "TELEMETRY_CLEAN"
    policy_reason = _policy_reason(
        status=status,
        active_count=len(active),
        unknown_count=len(unknown),
        historical_invalid_count=historical_invalid_count,
        quarantined_count=quarantined_count,
        reviewed_count=reviewed_count,
        unreviewed_count=unreviewed_count,
    )
    return {
        "telemetry_status": status,
        "invalid_timestamp_count": len(issues),
        "active_blocking_count": len(active),
        "unknown_requires_review": len(unknown),
        "historical_invalid_count": historical_invalid_count,
        "quarantined_count": quarantined_count,
        "reviewed_count": reviewed_count,
        "historical_reviewed_count": reviewed_count,
        "historical_quarantined_count": quarantined_count,
        "historical_unreviewed_count": unreviewed_count,
        "unquarantined_historical_count": unreviewed_count,
        "telemetry_acceptance_clear": not active and not unknown and unreviewed_count == 0,
        "telemetry_policy_reason": policy_reason,
        "active_blocking_issues": active,
        "historical_issues": historical_total,
        "quarantined_issues": quarantined,
        "unknown_issues": unknown,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _policy_reason(
    *,
    status: str,
    active_count: int,
    unknown_count: int,
    historical_invalid_count: int,
    quarantined_count: int,
    reviewed_count: int,
    unreviewed_count: int,
) -> str:
    if active_count > 0:
        return "Active invalid timestamps affect the current evidence window."
    if unknown_count > 0:
        return "Unknown timestamp issues require manual review."
    if unreviewed_count > 0:
        return "Historical invalid timestamps remain unreviewed."
    if historical_invalid_count > 0 and quarantined_count + reviewed_count >= historical_invalid_count:
        return "All historical invalid timestamps are quarantined or reviewed."
    if status == "TELEMETRY_CLEAN":
        return "No timestamp issues detected."
    return "Telemetry timestamp policy evaluated."


def _is_active(issue: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    if str(issue.get("status") or "").upper() == "CLOSED":
        return False
    first_seen = safe_parse_datetime(issue.get("first_seen_utc"), field_name="first_seen_utc", source="timestamp_issue").value
    window_start = safe_parse_datetime(context.get("latest_clean_window_start_utc"), field_name="latest_clean_window_start_utc", source="telemetry_context").value
    if first_seen is not None and window_start is not None and first_seen >= window_start:
        return True
    event_type = str(issue.get("event_type") or "").upper()
    source = str(issue.get("source", "")).lower()
    # If the issue has no parseable wrapper time but belongs to current operational tables, keep fail-closed.
    if first_seen is None and event_type in {"HEARTBEAT", "PAPER_TRADE_OPENED"}:
        return True
    return first_seen is None and any(marker in source for marker in ("heartbeats", "paper_trades"))


def _ledger_entry(issue: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    issues = ledger.get("issues", []) if isinstance(ledger, Mapping) else []
    if not isinstance(issues, list):
        return {}
    issue_id = issue.get("issue_id")
    issue_hash = raw_value_hash(issue.get("raw_value", ""))
    for item in issues:
        if not isinstance(item, Mapping):
            continue
        if item.get("issue_id") == issue_id or item.get("raw_value_hash") == issue_hash:
            return dict(item)
    return {}


def _safe_ignorable_source(source: str) -> bool:
    suffix = Path(source).suffix.lower()
    return suffix in {".md", ".ps1"} or "docs" in source or "readme" in source
