"""SQLite vs JSONL halt event comparison."""

from __future__ import annotations

from typing import Any, Mapping


def compare_sqlite_jsonl(sqlite_events: list[Mapping[str, Any]], jsonl_events: list[Mapping[str, Any]]) -> dict[str, Any]:
    sqlite_keys = {_key(event) for event in sqlite_events}
    jsonl_keys = {_key(event) for event in jsonl_events}
    return {
        "sqlite_halt_event_count": len(sqlite_events),
        "jsonl_halt_event_count": len(jsonl_events),
        "matching_event_count": len(sqlite_keys & jsonl_keys),
        "sqlite_only_event_count": len(sqlite_keys - jsonl_keys),
        "jsonl_only_event_count": len(jsonl_keys - sqlite_keys),
        "sqlite_only_examples": _examples(sqlite_events, sqlite_keys - jsonl_keys),
        "jsonl_only_examples": _examples(jsonl_events, jsonl_keys - sqlite_keys),
        "comparison_status": _status(sqlite_events, jsonl_events, sqlite_keys, jsonl_keys),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _key(event: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(event.get("timestamp_utc", "")), str(event.get("event_type", "")), str(event.get("halt_code", "")))


def _examples(events: list[Mapping[str, Any]], keys: set[tuple[str, str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for event in events:
        if _key(event) in keys:
            output.append({key: event.get(key, "") for key in ("source", "timestamp_utc", "event_type", "halt_code", "detector_miss_reason")})
        if len(output) >= 20:
            break
    return output


def _status(sqlite_events: list[Mapping[str, Any]], jsonl_events: list[Mapping[str, Any]], sqlite_keys: set[tuple[str, str, str]], jsonl_keys: set[tuple[str, str, str]]) -> str:
    if not sqlite_events and not jsonl_events:
        return "NO_HALT_EVENTS_FOUND"
    if sqlite_keys == jsonl_keys:
        return "SQLITE_JSONL_HALT_EVENTS_ALIGNED"
    if sqlite_events and not jsonl_events:
        return "SQLITE_ONLY_HALT_EVENTS"
    if jsonl_events and not sqlite_events:
        return "JSONL_ONLY_HALT_EVENTS"
    return "SQLITE_JSONL_HALT_EVENTS_DIVERGED"
