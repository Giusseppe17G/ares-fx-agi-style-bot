"""Halt event scanner for SQLite rows and JSONL log lines."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


HALT_TERMS = ("PAPER_DAILY_DRAWDOWN_HALT", "PAPER_DAILY_DRAWDOWN", "PAPER_SHADOW_HALTED")
STATE_TERMS = ("shadow_paused", "halt_reason", "latest_exit_reason", "paused_reason")
# Values that make an exit/pause reason halt evidence. A normal exit reason such as
# TAKE_PROFIT or STOP_LOSS is not halt evidence and must never be scanned as a halt event.
HALT_STATE_VALUE_TERMS = ("HALT", "DRAWDOWN", "PAUSED", "PAPER_STATE_ERROR", "CONFIG_ERROR")


def scan_sqlite_halt_events(sqlite_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows_by_table = sqlite_payload.get("rows_by_table") if isinstance(sqlite_payload.get("rows_by_table"), Mapping) else {}
    events: list[dict[str, Any]] = []
    for table, rows in rows_by_table.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            hit = _row_hit(row)
            if hit["matched"]:
                events.append(_event_from_row(source=f"sqlite:{table}", table=str(table), row=row, hit=hit))
    return sorted(events, key=lambda item: item.get("timestamp_utc") or "")


def scan_jsonl_halt_events(log_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(log_dir)
    events: list[dict[str, Any]] = []
    if not root.exists():
        return events
    for path in sorted(root.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line_no, line in enumerate(handle, start=1):
                    payload = _loads(line)
                    if not payload:
                        continue
                    hit = _row_hit(payload)
                    if hit["matched"]:
                        events.append(_event_from_row(source=f"jsonl:{path.name}:{line_no}", table="jsonl", row=payload, hit=hit))
        except OSError:
            continue
    return sorted(events, key=lambda item: item.get("timestamp_utc") or "")


def current_is_halt_event_match(event: Mapping[str, Any]) -> bool:
    source = str(event.get("source", ""))
    if not (source.startswith("sqlite:events") or source.startswith("jsonl:")):
        return False
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    text = " ".join(str(item) for item in (event.get("event_type"), event.get("message"), payload.get("halt_reason"), payload.get("alert_code")))
    return "PAPER_DAILY_DRAWDOWN" in text or "PAPER_DAILY_DRAWDOWN_HALT" in text


def explain_detector_miss(event: Mapping[str, Any]) -> str:
    if current_is_halt_event_match(event):
        return "MATCHES_CURRENT_DETECTOR"
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    row_keys = set(event.keys())
    payload_keys = set(payload.keys())
    combined = " ".join(str(value) for value in _string_values(event)).upper()
    if not (str(event.get("source", "")).startswith("sqlite:events") or str(event.get("source", "")).startswith("jsonl:")):
        return "SOURCE_NOT_IN_CURRENT_EVENTS_DATASET"
    if "PAPER_DAILY_DRAWDOWN" not in combined and "PAPER_SHADOW_HALTED" not in combined:
        return "NO_DRAWDOWN_TOKEN_IN_CURRENT_EVENT_OBJECT"
    if event.get("source", "").startswith("sqlite:alerts") and "alert_code" in row_keys and "alert_code" not in payload_keys:
        return "ALERT_CODE_ONLY_IN_SQLITE_COLUMN_NOT_PAYLOAD"
    if event.get("source", "").startswith("sqlite:operational_state"):
        return "HALT_STATE_STORED_IN_OPERATIONAL_STATE_NOT_EVENTS_DATASET"
    if "PAPER_SHADOW_HALTED" in combined and "PAPER_DAILY_DRAWDOWN" not in combined:
        return "EVENT_RENAMED_TO_PAPER_SHADOW_HALTED_WITHOUT_DRAWDOWN_TOKEN"
    if combined != " ".join(str(value) for value in _current_detector_fields(event)):
        return "HALT_TOKEN_OUTSIDE_CURRENT_DETECTOR_FIELDS"
    return "CASE_OR_FIELD_MAPPING_MISMATCH"


def summarize_events(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    invalid_ts = [event for event in events if event.get("timestamp_parse_status") != "OK"]
    no_tz = [event for event in events if event.get("timestamp_timezone") == "MISSING"]
    duplicates = _duplicates(events)
    return {
        "event_count": len(events),
        "invalid_timestamp_count": len(invalid_ts),
        "timezone_missing_count": len(no_tz),
        "duplicate_event_count": len(duplicates),
        "first_timestamp_utc": events[0].get("timestamp_utc", "") if events else "",
        "latest_timestamp_utc": events[-1].get("timestamp_utc", "") if events else "",
        "event_types": _counts(event.get("event_type", "") for event in events),
        "halt_codes": _counts(event.get("halt_code", "") for event in events),
        "sources": _counts(str(event.get("source", "")).split(":")[0] for event in events),
        "duplicates": duplicates[:100],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _event_from_row(*, source: str, table: str, row: Mapping[str, Any], hit: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("_payload") if isinstance(row.get("_payload"), Mapping) else row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
    event = {
        "source": source,
        "table": table,
        "row_id": row.get("_rowid_") or row.get("id") or "",
        "event_type": str(row.get("event_type") or row.get("event_name") or row.get("event_code") or payload.get("event_type") or payload.get("event_name") or payload.get("event_code") or row.get("alert_code") or payload.get("alert_code") or ""),
        "event_name": str(row.get("event_name") or payload.get("event_name") or ""),
        "event_code": str(row.get("event_code") or payload.get("event_code") or row.get("alert_code") or payload.get("alert_code") or ""),
        "halt_code": str(hit.get("halt_code") or ""),
        "halt_evidence_class": str(hit.get("halt_evidence_class") or ""),
        "timestamp_utc": _timestamp(row, payload),
        "message": str(row.get("message") or payload.get("message") or ""),
        "payload": dict(payload),
        "shadow_paused": _coalesce(row, payload, "shadow_paused"),
        "halt_reason": _coalesce(row, payload, "halt_reason") or _coalesce(row, payload, "paused_reason"),
        "latest_exit_reason": _coalesce(row, payload, "latest_exit_reason"),
        "matched_terms": ",".join(hit.get("matched_terms", [])),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    event.update(_timestamp_status(event["timestamp_utc"]))
    event["current_is_halt_event_match"] = current_is_halt_event_match(event)
    event["detector_miss_reason"] = explain_detector_miss(event)
    return event


def _row_hit(row: Mapping[str, Any]) -> dict[str, Any]:
    # Only row VALUES are searched for halt tokens. Scanning column names too made any
    # table with a `halt_reason`/`latest_exit_reason` column look like halt evidence.
    haystack = " ".join(str(value) for value in _value_strings(row)).upper()
    matched = [term for term in HALT_TERMS if term in haystack]
    state_matches = _state_hits(row)
    evidence_class = "HALT_TOKEN" if matched else ("HALT_STATE_FIELD" if state_matches else "")
    return {
        "matched": bool(matched or state_matches),
        "matched_terms": matched + state_matches,
        "halt_code": matched[0] if matched else "",
        "halt_evidence_class": evidence_class,
    }


def _state_hits(value: Any) -> list[str]:
    hits: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text == "payload_json":
                try:
                    hits.extend(_state_hits(json.loads(str(item or ""))))
                except Exception:
                    pass
                continue
            if key_text == "shadow_paused" and _truthy(item):
                hits.append("shadow_paused")
            elif key_text in {"halt_reason", "paused_reason"} and str(item or "").strip():
                hits.append(key_text)
            elif key_text == "latest_exit_reason" and _halt_state_value(item):
                hits.append(key_text)
            else:
                hits.extend(_state_hits(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            hits.extend(_state_hits(item))
    return sorted(set(hits))


def _halt_state_value(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return bool(text) and any(term in text for term in HALT_STATE_VALUE_TERMS)


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _value_strings(value: Any) -> Iterable[str]:
    """Yield only the values of a row (recursing into payload_json), never the keys."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) == "payload_json":
                try:
                    yield from _value_strings(json.loads(str(item or "")))
                except Exception:
                    yield str(item)
            else:
                yield from _value_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _value_strings(item)
    else:
        yield str(value)


def _string_values(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) == "payload_json":
                yield str(key)
                try:
                    yield from _string_values(json.loads(str(item or "")))
                except Exception:
                    yield str(item)
            else:
                yield str(key)
                yield from _string_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _string_values(item)
    else:
        yield str(value)


def _current_detector_fields(event: Mapping[str, Any]) -> list[Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    return [event.get("event_type"), event.get("message"), payload.get("halt_reason"), payload.get("alert_code")]


def _timestamp(row: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    for key in ("timestamp_utc", "created_at_utc", "updated_at_utc", "paused_at_utc", "closed_at_utc", "opened_at_utc"):
        value = row.get(key) or payload.get(key)
        if value:
            return str(value)
    return ""


def _timestamp_status(value: Any) -> dict[str, str]:
    if not value:
        return {"timestamp_parse_status": "EMPTY", "timestamp_timezone": "MISSING"}
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return {"timestamp_parse_status": "INVALID", "timestamp_timezone": "UNKNOWN"}
    tz_status = "PRESENT" if parsed.tzinfo is not None else "MISSING"
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return {"timestamp_parse_status": "OK", "timestamp_timezone": tz_status, "timestamp_utc": parsed.isoformat() if parsed.tzinfo else str(value)}


def _coalesce(row: Mapping[str, Any], payload: Mapping[str, Any], key: str) -> Any:
    return row.get(key) if row.get(key) not in {None, ""} else payload.get(key, "")


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(str(value or ""))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _duplicates(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, str], int] = {}
    duplicates: list[dict[str, Any]] = []
    for event in events:
        key = (str(event.get("timestamp_utc", "")), str(event.get("event_type", "")), str(event.get("halt_code", "")))
        seen[key] = seen.get(key, 0) + 1
    for key, count in seen.items():
        if count > 1:
            duplicates.append({"timestamp_utc": key[0], "event_type": key[1], "halt_code": key[2], "count": count})
    return duplicates
