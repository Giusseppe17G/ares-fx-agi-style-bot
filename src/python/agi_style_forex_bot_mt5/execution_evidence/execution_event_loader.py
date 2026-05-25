"""Load execution-related evidence from JSONL, reports and SQLite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


KEYWORDS = ("order_send", "order_check", "execution_attempted")


def load_execution_evidence_events(
    *,
    sqlite_path: str | Path | None = None,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
) -> list[dict[str, Any]]:
    """Load candidate evidence records without interpreting them."""

    rows: list[dict[str, Any]] = []
    rows.extend(_load_jsonl(Path(log_dir)))
    rows.extend(_load_reports(Path(reports_root)))
    if sqlite_path is not None and Path(sqlite_path).exists():
        rows.extend(_load_sqlite(Path(sqlite_path)))
    return rows


def _load_jsonl(log_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not log_dir.exists():
        return rows
    for path in sorted(log_dir.glob("*.jsonl")):
        try:
            for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    payload = {"raw_message": line}
                rows.append(_base_record(payload, source_type="jsonl", source=str(path), row=str(index)))
        except OSError:
            continue
    return rows


def _load_reports(reports_root: Path) -> list[dict[str, Any]]:
    targets = [
        reports_root / "forward_evidence" / "evidence_summary.json",
        reports_root / "forward_evidence" / "operational_acceptance.json",
        reports_root / "forward_evidence" / "paper_trade_audit.json",
    ]
    rows: list[dict[str, Any]] = []
    for path in targets:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"raw_message": path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""}
        rows.append(_base_record(payload, source_type="report", source=str(path), row=""))
    return rows


def _load_sqlite(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    db = TelemetryDatabase(path)
    try:
        for table in ("events", "heartbeats", "alerts", "paper_trade_events"):
            try:
                for index, row in enumerate(db.fetch_all(table), start=1):
                    payload = _row_payload(row)
                    rows.append(_base_record(payload, source_type="sqlite", source=table, row=str(index)))
            except Exception:
                continue
    finally:
        db.close()
    return rows


def _row_payload(row: Any) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
        if hasattr(row, "keys"):
            for key in ("timestamp_utc", "event_type", "alert_code", "severity", "mode", "message"):
                if key not in payload and key in row.keys():
                    payload[key] = row[key]
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _base_record(payload: Mapping[str, Any], *, source_type: str, source: str, row: str) -> dict[str, Any]:
    payload_dict = dict(payload)
    return {
        "timestamp_utc": payload_dict.get("timestamp_utc"),
        "source_type": source_type,
        "source": source,
        "row": row,
        "mode": payload_dict.get("mode"),
        "event_type": payload_dict.get("event_type"),
        "raw_message": payload_dict.get("message") or payload_dict.get("raw_message") or "",
        "alert_code": payload_dict.get("alert_code"),
        "severity": payload_dict.get("severity"),
        "payload": payload_dict,
        "execution_attempted": payload_dict.get("execution_attempted"),
        "order_send_called": payload_dict.get("order_send_called"),
        "order_check_called": payload_dict.get("order_check_called"),
    }
