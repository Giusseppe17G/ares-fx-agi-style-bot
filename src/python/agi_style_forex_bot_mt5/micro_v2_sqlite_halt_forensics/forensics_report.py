"""Report orchestration for Micro V2 SQLite halt forensics."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from .detector_diagnostics import diagnose_current_detector
from .halt_event_scanner import scan_jsonl_halt_events, scan_sqlite_halt_events, summarize_events
from .jsonl_comparator import compare_sqlite_jsonl
from .sqlite_introspection import QUERIES_USED, inspect_sqlite


def run_micro_v2_sqlite_halt_forensics(
    *,
    sqlite_path: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    log_dir: str | Path | None = None,
    output_dir: str | Path = "data/reports/micro_v2_sqlite_halt_forensics",
) -> dict[str, Any]:
    sqlite_path = Path(sqlite_path)
    effective_log_dir = _infer_log_dir(sqlite_path, log_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    sqlite_payload = inspect_sqlite(sqlite_path)
    sqlite_events = scan_sqlite_halt_events(sqlite_payload)
    jsonl_events = scan_jsonl_halt_events(effective_log_dir)
    all_events = [*sqlite_events, *jsonl_events]
    detector = diagnose_current_detector(all_events)
    comparison = compare_sqlite_jsonl(sqlite_events, jsonl_events)
    schema_inventory = _schema_inventory(sqlite_payload)
    summary = {
        "mode": "micro-v2-sqlite-halt-forensics",
        "sqlite_path": str(sqlite_path),
        "log_dir": str(effective_log_dir),
        "forensics_status": _status(sqlite_payload, all_events, detector),
        "sqlite_table_count": len(schema_inventory.get("tables", [])),
        "sqlite_halt_event_count": len(sqlite_events),
        "jsonl_halt_event_count": len(jsonl_events),
        "total_halt_event_count": len(all_events),
        "current_detector_match_count": detector.get("current_detector_match_count", 0),
        "current_detector_miss_count": detector.get("current_detector_miss_count", 0),
        "halt_token_event_count": detector.get("halt_token_event_count", 0),
        "halt_state_field_event_count": detector.get("halt_state_field_event_count", 0),
        "in_scope_detector_miss_count": detector.get("in_scope_detector_miss_count", 0),
        "out_of_scope_detector_miss_count": detector.get("out_of_scope_detector_miss_count", 0),
        "likely_root_causes": detector.get("likely_root_causes", []),
        "sqlite_vs_jsonl_status": comparison.get("comparison_status", ""),
        "invalid_timestamp_count": summarize_events(all_events).get("invalid_timestamp_count", 0),
        "timezone_missing_count": summarize_events(all_events).get("timezone_missing_count", 0),
        "duplicate_event_count": summarize_events(all_events).get("duplicate_event_count", 0),
        "queries_used": QUERIES_USED,
        "recommended_next_action": "Review forensic outputs before changing halt detection logic.",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, schema_inventory, sqlite_events, jsonl_events, detector, comparison)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _infer_log_dir(sqlite_path: Path, log_dir: str | Path | None) -> Path:
    if log_dir is not None:
        candidate = Path(log_dir)
        if str(candidate).replace("\\", "/") != "data/logs":
            return candidate
    if "v2-dryrun" in sqlite_path.name:
        return Path("data/logs/forward-shadow-v2-dryrun")
    return Path(log_dir or "data/logs")


def _status(sqlite_payload: Mapping[str, Any], events: list[Mapping[str, Any]], detector: Mapping[str, Any]) -> str:
    if sqlite_payload.get("sqlite_read_error"):
        return "SQLITE_HALT_FORENSICS_SQLITE_READ_ERROR"
    if not events:
        return "SQLITE_HALT_FORENSICS_NO_HALT_EVENTS_FOUND"
    if int(detector.get("in_scope_detector_miss_count", 0) or 0) > 0:
        return "SQLITE_HALT_FORENSICS_DETECTOR_MISS_CONFIRMED"
    if int(detector.get("out_of_scope_detector_miss_count", 0) or 0) > 0:
        return "SQLITE_HALT_FORENSICS_DETECTOR_SCOPE_GAP"
    return "SQLITE_HALT_FORENSICS_HALT_EVENTS_DETECTED"


def _schema_inventory(sqlite_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sqlite_exists": sqlite_payload.get("sqlite_exists", False),
        "sqlite_path": sqlite_payload.get("sqlite_path", ""),
        "tables": [
            {
                "name": table.get("name", ""),
                "type": table.get("type", ""),
                "row_count": table.get("row_count", 0),
                "column_names": table.get("column_names", []),
                "sql": table.get("sql", ""),
            }
            for table in sqlite_payload.get("tables", [])
        ],
        "queries_used": sqlite_payload.get("queries_used", QUERIES_USED),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    schema_inventory: Mapping[str, Any],
    sqlite_events: list[Mapping[str, Any]],
    jsonl_events: list[Mapping[str, Any]],
    detector: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> list[Path]:
    paths = [
        output / "sqlite_halt_forensics_summary.json",
        output / "schema_inventory.json",
        output / "halt_detector_diagnostics.json",
        output / "sqlite_vs_jsonl_comparison.json",
        output / "halt_events.csv",
        output / "queries_used.sql",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], schema_inventory)
    _write_json(paths[2], detector)
    _write_json(paths[3], comparison)
    _write_csv(paths[4], [*_event_rows(sqlite_events, "sqlite"), *_event_rows(jsonl_events, "jsonl")])
    paths[5].write_text("\n".join(f"-- {query}" for query in QUERIES_USED) + "\n", encoding="utf-8")
    paths[6].write_text(f"<html><body><h1>Micro V2 SQLite Halt Forensics</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _event_rows(events: list[Mapping[str, Any]], storage: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        rows.append(
            {
                "storage": storage,
                "source": event.get("source", ""),
                "table": event.get("table", ""),
                "row_id": event.get("row_id", ""),
                "timestamp_utc": event.get("timestamp_utc", ""),
                "timestamp_parse_status": event.get("timestamp_parse_status", ""),
                "timestamp_timezone": event.get("timestamp_timezone", ""),
                "event_type": event.get("event_type", ""),
                "event_code": event.get("event_code", ""),
                "halt_code": event.get("halt_code", ""),
                "halt_evidence_class": event.get("halt_evidence_class", ""),
                "halt_reason": event.get("halt_reason", ""),
                "shadow_paused": event.get("shadow_paused", ""),
                "latest_exit_reason": event.get("latest_exit_reason", ""),
                "current_is_halt_event_match": event.get("current_is_halt_event_match", False),
                "detector_miss_reason": event.get("detector_miss_reason", ""),
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = [
        "storage",
        "source",
        "table",
        "row_id",
        "timestamp_utc",
        "timestamp_parse_status",
        "timestamp_timezone",
        "event_type",
        "event_code",
        "halt_code",
        "halt_evidence_class",
        "halt_reason",
        "shadow_paused",
        "latest_exit_reason",
        "current_is_halt_event_match",
        "detector_miss_reason",
        "execution_attempted",
        "order_send_called",
        "order_check_called",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
