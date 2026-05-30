"""Offline rejection labeling audit for legacy and new taxonomy events."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset

from .rejection_taxonomy import NEW_REJECTION_EVENTS, is_suspected_misclassified_symbol_rejection


def run_rejection_labeling_audit(
    *,
    base_sqlite: str | Path = "data/sqlite/forward-shadow-stable.sqlite3",
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    base_log_dir: str | Path = "data/logs/forward-shadow-stable",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    output_dir: str | Path = "data/reports/rejection_labeling_audit",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = load_dry_run_dataset(sqlite_path=base_sqlite, log_dir=base_log_dir, label="base")
    v2 = load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2")
    events = [*_tag(base.get("events", []), "base"), *_tag(v2.get("events", []), "v2")]
    taxonomy = _taxonomy_counts(events)
    suspected = _suspected_rows(events)
    legacy = _legacy_rows(events)
    status, action = _classify(taxonomy, suspected)
    summary = {
        "mode": "rejection-labeling-audit",
        "rejection_labeling_status": status,
        **taxonomy,
        "suspected_misclassified_symbol_rejections": len(suspected),
        "legacy_symbol_rejected_count": len(legacy),
        "new_taxonomy_available": True,
        "reports_root": str(reports_root),
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, suspected, legacy)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _tag(events: list[Mapping[str, Any]], label: str) -> list[dict[str, Any]]:
    return [{**dict(event), "runtime_label": label} for event in events]


def _taxonomy_counts(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {
        "symbol_rejected_count": 0,
        "stale_tick_rejection_count": 0,
        "market_closed_rejection_count": 0,
        "future_signal_rejection_count": 0,
        "invalid_market_snapshot_rejection_count": 0,
    }
    for event in events:
        event_type = str(event.get("event_type", "")).upper()
        if event_type == "SYMBOL_REJECTED":
            counts["symbol_rejected_count"] += 1
        elif event_type == "STALE_TICK_REJECTION":
            counts["stale_tick_rejection_count"] += 1
        elif event_type == "MARKET_CLOSED_REJECTION":
            counts["market_closed_rejection_count"] += 1
        elif event_type == "FUTURE_SIGNAL_REJECTION":
            counts["future_signal_rejection_count"] += 1
        elif event_type == "INVALID_MARKET_SNAPSHOT_REJECTION":
            counts["invalid_market_snapshot_rejection_count"] += 1
    return counts


def _suspected_rows(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        if not is_suspected_misclassified_symbol_rejection(str(event.get("event_type", "")), payload, str(event.get("message", ""))):
            continue
        rows.append(
            {
                "runtime_label": event.get("runtime_label", ""),
                "symbol": event.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "",
                "event_type": event.get("event_type", ""),
                "message": event.get("message", ""),
                "reject_code": payload.get("reject_code", ""),
                "reject_reason": payload.get("reject_reason", payload.get("reason", "")),
                "tick_time_status": payload.get("tick_time_status", ""),
                "market_is_probably_closed": payload.get("market_is_probably_closed", False),
                "normalization_reason": payload.get("normalization_reason", ""),
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    return rows


def _legacy_rows(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if str(event.get("event_type", "")).upper() != "SYMBOL_REJECTED":
            continue
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        rows.append(
            {
                "runtime_label": event.get("runtime_label", ""),
                "symbol": event.get("symbol") or payload.get("symbol") or "",
                "message": event.get("message", ""),
                "reject_code": payload.get("reject_code", ""),
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    return rows


def _classify(taxonomy: Mapping[str, Any], suspected: list[Mapping[str, Any]]) -> tuple[str, str]:
    new_count = sum(int(taxonomy.get(key, 0) or 0) for key in ("stale_tick_rejection_count", "market_closed_rejection_count", "future_signal_rejection_count", "invalid_market_snapshot_rejection_count"))
    if suspected and new_count == 0:
        return "REJECTION_LABELING_LEGACY_MISCLASSIFICATIONS_ONLY", "KEEP_COLLECTING_RUNTIME_DATA_WITH_NEW_REJECTION_TAXONOMY"
    if suspected and new_count > 0:
        return "REJECTION_LABELING_STILL_MISCLASSIFIED", "REVIEW_REMAINING_SYMBOL_REJECTED_PAYLOADS"
    if new_count > 0:
        return "REJECTION_LABELING_FIXED", "MONITOR_NEW_TAXONOMY_COUNTS_OFFLINE"
    return "REJECTION_LABELING_NEEDS_MORE_RUNTIME_DATA", "KEEP_COLLECTING_RUNTIME_DATA"


def _write_reports(output: Path, summary: Mapping[str, Any], suspected: list[Mapping[str, Any]], legacy: list[Mapping[str, Any]]) -> list[Path]:
    paths = [
        output / "rejection_labeling_summary.json",
        output / "rejection_taxonomy.json",
        output / "suspected_misclassified_rejections.csv",
        output / "legacy_rejections.csv",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_json(paths[1], {key: summary.get(key) for key in ("new_taxonomy_available", "symbol_rejected_count", "stale_tick_rejection_count", "market_closed_rejection_count", "future_signal_rejection_count", "invalid_market_snapshot_rejection_count")})
    _write_csv(paths[2], suspected)
    _write_csv(paths[3], legacy)
    paths[4].write_text(_recommendations(summary), encoding="utf-8")
    paths[5].write_text(f"<html><body><h1>Rejection Labeling Audit</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    return paths


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Rejection Labeling Audit

Status: `{summary.get('rejection_labeling_status')}`

Suspected legacy misclassifications: `{summary.get('suspected_misclassified_symbol_rejections')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This audit is offline/read-only. It does not rewrite historical SQLite/log events and does not authorize demo/live execution.
"""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted", "order_send_called", "order_check_called"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key in {"execution_attempted", "order_send_called", "order_check_called"} else "") for key in fieldnames})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
