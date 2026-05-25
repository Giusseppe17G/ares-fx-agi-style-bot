"""Classify order/execution evidence without false positives."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


BLOCKING_CLASSES = {"REAL_ORDER_SEND_TRUE", "REAL_ORDER_CHECK_TRUE", "EXECUTION_ATTEMPTED_TRUE", "UNKNOWN_REQUIRES_REVIEW"}
SAFE_CLASSES = {"SAFE_BOOLEAN_FALSE", "TEXT_ONLY_MENTION", "DOC_OR_COMMAND_REFERENCE", "HISTORICAL_REVIEWED"}
ORDER_FIELDS = {"order_send_called", "order_check_called", "execution_attempted"}


def scan_order_call_evidence(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return classified findings for order/execution evidence records."""

    findings: list[dict[str, Any]] = []
    for record in records:
        for path, value in _walk(record.get("payload", {})):
            lowered_path = path.lower()
            lowered_value = str(value).lower()
            if any(field in lowered_path for field in ORDER_FIELDS) or "order_send" in lowered_value or "order_check" in lowered_value or "execution_attempted" in lowered_value:
                classification = classify_finding(field_path=path, value=value, record=record)
                findings.append(
                    {
                        "classification": classification,
                        "timestamp_utc": record.get("timestamp_utc"),
                        "source_type": record.get("source_type"),
                        "source": record.get("source"),
                        "row": record.get("row"),
                        "mode": record.get("mode"),
                        "event_type": record.get("event_type"),
                        "alert_code": record.get("alert_code"),
                        "severity": record.get("severity"),
                        "field_path": path,
                        "field_value": _short_value(value),
                        "value_kind": _value_kind(value),
                        "raw_message": _short_value(record.get("raw_message", "")),
                        "is_blocking": classification in BLOCKING_CLASSES,
                        "execution_attempted": False,
                    }
                )
    return findings


def classify_finding(*, field_path: str, value: Any, record: Mapping[str, Any]) -> str:
    """Classify one evidence occurrence."""

    path = field_path.lower()
    source = str(record.get("source", "")).lower()
    text = str(value).lower()
    if path.endswith("order_send_called"):
        if value is True:
            return "REAL_ORDER_SEND_TRUE"
        if value is False:
            return "SAFE_BOOLEAN_FALSE"
        return "UNKNOWN_REQUIRES_REVIEW"
    if path.endswith("order_check_called"):
        if value is True:
            return "REAL_ORDER_CHECK_TRUE"
        if value is False:
            return "SAFE_BOOLEAN_FALSE"
        return "UNKNOWN_REQUIRES_REVIEW"
    if path.endswith("execution_attempted"):
        if value is True:
            return "EXECUTION_ATTEMPTED_TRUE"
        if value is False:
            return "SAFE_BOOLEAN_FALSE"
        return "UNKNOWN_REQUIRES_REVIEW"
    if isinstance(value, str):
        if _is_doc_or_command(source, path, text):
            return "DOC_OR_COMMAND_REFERENCE"
        if _is_safe_text_mention(text):
            return "TEXT_ONLY_MENTION"
        if "order_send" in text or "order_check" in text or "execution_attempted" in text:
            return "UNKNOWN_REQUIRES_REVIEW"
    return "TEXT_ONLY_MENTION"


def summarize_findings(findings: list[Mapping[str, Any]]) -> dict[str, Any]:
    blocking = [item for item in findings if bool(item.get("is_blocking"))]
    false_positive = [
        item
        for item in findings
        if str(item.get("classification")) in {"SAFE_BOOLEAN_FALSE", "TEXT_ONLY_MENTION", "DOC_OR_COMMAND_REFERENCE", "HISTORICAL_REVIEWED"}
    ]
    real_send = any(item.get("classification") == "REAL_ORDER_SEND_TRUE" for item in findings)
    real_check = any(item.get("classification") == "REAL_ORDER_CHECK_TRUE" for item in findings)
    attempted = any(item.get("classification") == "EXECUTION_ATTEMPTED_TRUE" for item in findings)
    unknown = sum(1 for item in findings if item.get("classification") == "UNKNOWN_REQUIRES_REVIEW")
    if real_send or real_check or attempted:
        status = "EXECUTION_EVIDENCE_BLOCKED_REAL_ATTEMPT"
    elif unknown:
        status = "EXECUTION_EVIDENCE_UNKNOWN_REVIEW_REQUIRED"
    elif false_positive:
        status = "EXECUTION_EVIDENCE_FALSE_POSITIVE_ONLY"
    else:
        status = "EXECUTION_EVIDENCE_CLEAR"
    return {
        "execution_evidence_status": status,
        "real_order_send_detected": real_send,
        "real_order_check_detected": real_check,
        "execution_attempted_detected": attempted,
        "false_positive_mentions": len(false_positive),
        "unknown_requires_review": unknown,
        "blocking_findings": blocking,
        "false_positive_findings": false_positive,
        "findings_count": len(findings),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _walk(value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, item
            yield from _walk(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            yield path, item
            yield from _walk(item, path)


def _is_safe_text_mention(text: str) -> bool:
    safe_fragments = (
        "not called",
        "was not called",
        "never called",
        "prohibited",
        "blocked",
        "false",
        "execution_attempted=false",
        "order_send_called=false",
        "order_check_called=false",
        "do not call",
    )
    return any(fragment in text for fragment in safe_fragments)


def _is_doc_or_command(source: str, path: str, text: str) -> bool:
    doc_source = any(marker in source for marker in ("docs", "readme", "checklist", "commands", "deployment_pack", ".md", ".ps1"))
    command_text = "py -m agi_style_forex_bot_mt5.cli" in text or "powershell" in text or "--mode" in text
    return doc_source or command_text or "recommended_next_command" in path or "commands_to_run_next" in path


def _value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean_true" if value else "boolean_false"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "string_mention"
    return type(value).__name__


def _short_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True)
    else:
        text = str(value)
    return text[:500]
