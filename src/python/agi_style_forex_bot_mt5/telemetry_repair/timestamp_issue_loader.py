"""Load timestamp issues from forward telemetry artifacts without mutation."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


TIMESTAMP_FIELD_MARKERS = ("timestamp", "time_utc", "opened_at", "closed_at", "entry_time", "exit_time", "heartbeat")


def load_timestamp_issues(
    *,
    sqlite_path: str | Path | None = None,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return detected timestamp issues and evidence-window context."""

    records = _load_records(sqlite_path=sqlite_path, log_dir=Path(log_dir), reports_root=Path(reports_root))
    context = _window_context(records, sqlite_path)
    issues: list[dict[str, Any]] = []
    for record in records:
        for field_path, value in _walk(record.get("payload", {})):
            if not _looks_like_timestamp_field(field_path):
                continue
            issue = _issue_for_value(record=record, field_path=field_path, value=value, context=context)
            if issue:
                issues.append(issue)
    return issues, context


def _load_records(*, sqlite_path: str | Path | None, log_dir: Path, reports_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    records.extend(_load_jsonl(log_dir))
    records.extend(_load_reports(reports_root))
    if sqlite_path is not None and Path(sqlite_path).exists():
        records.extend(_load_sqlite(Path(sqlite_path)))
    return records


def _load_jsonl(log_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not log_dir.exists():
        return records
    for path in sorted(log_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"raw_message": line}
            records.append(_record(payload, source_type="jsonl", source=str(path), row=str(index)))
    return records


def _load_reports(reports_root: Path) -> list[dict[str, Any]]:
    targets = [
        reports_root / "forward_evidence" / "evidence_summary.json",
        reports_root / "forward_evidence" / "forward_metrics.json",
        reports_root / "forward_evidence" / "paper_trade_audit.json",
        reports_root / "paper_state" / "paper_state_report.json",
    ]
    records: list[dict[str, Any]] = []
    for path in targets:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            payload = {"raw_message": path.read_text(encoding="utf-8", errors="replace")}
        except OSError:
            continue
        records.append(_record(payload, source_type="report", source=str(path), row=""))
    return records


def _load_sqlite(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    db = TelemetryDatabase(path)
    try:
        for table in ("events", "heartbeats", "alerts", "paper_trades", "paper_trade_events", "paper_performance_snapshots", "operational_state"):
            try:
                rows = db.fetch_all(table) if table != "paper_trades" else db.fetch_paper_trades()
            except Exception:
                continue
            for index, row in enumerate(rows, start=1):
                payload = _row_payload(row)
                for key in ("timestamp_utc", "opened_at_utc", "closed_at_utc", "updated_at_utc", "event_type", "alert_code", "severity", "mode", "message"):
                    try:
                        if key not in payload and key in row.keys():
                            payload[key] = row[key]
                    except Exception:
                        continue
                records.append(_record(payload, source_type="sqlite", source=table, row=str(index)))
    finally:
        db.close()
    return records


def _row_payload(row: Any) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _record(payload: Mapping[str, Any], *, source_type: str, source: str, row: str) -> dict[str, Any]:
    payload_dict = dict(payload)
    return {
        "source_type": source_type,
        "source": source,
        "row": row,
        "timestamp_utc": payload_dict.get("timestamp_utc"),
        "event_type": payload_dict.get("event_type"),
        "alert_code": payload_dict.get("alert_code"),
        "severity": payload_dict.get("severity"),
        "mode": payload_dict.get("mode"),
        "raw_message": payload_dict.get("message") or payload_dict.get("raw_message") or "",
        "payload": payload_dict,
    }


def _window_context(records: list[Mapping[str, Any]], sqlite_path: str | Path | None) -> dict[str, Any]:
    parsed_times: list[datetime] = []
    reset_times: list[datetime] = []
    for record in records:
        record_time = safe_parse_datetime(record.get("timestamp_utc"), field_name="timestamp_utc", source=str(record.get("source"))).value
        if record_time:
            parsed_times.append(record_time)
        event_type = str(record.get("event_type") or "").upper()
        if event_type in {"PAPER_TRADE_MANUAL_CLOSE", "SHADOW_MANUALLY_PAUSED", "SHADOW_MANUALLY_RESUMED"} and record_time:
            reset_times.append(record_time)
    if sqlite_path is not None and Path(sqlite_path).exists():
        db = TelemetryDatabase(sqlite_path)
        try:
            state = db.get_operational_state()
            for key in ("paused_at_utc", "resumed_at_utc"):
                parsed = safe_parse_datetime(state.get(key), field_name=key, source="operational_state").value
                if parsed:
                    reset_times.append(parsed)
        finally:
            db.close()
    now = datetime.now(timezone.utc)
    latest_seen = max(parsed_times) if parsed_times else now
    latest_reset = max(reset_times) if reset_times else None
    window_start = latest_reset or (latest_seen - timedelta(hours=24))
    return {
        "latest_seen_utc": latest_seen.isoformat(),
        "latest_reset_utc": latest_reset.isoformat() if latest_reset else None,
        "latest_clean_window_start_utc": window_start.isoformat(),
        "evidence_window_hours": 24,
    }


def _issue_for_value(*, record: Mapping[str, Any], field_path: str, value: Any, context: Mapping[str, Any]) -> dict[str, Any] | None:
    if (value is None or str(value).strip() == "") and not _missing_timestamp_is_critical(field_path, record):
        return None
    result = safe_parse_datetime(value, field_name=field_path, source=str(record.get("source")))
    now = datetime.now(timezone.utc)
    warning = result.warning
    if result.value is not None:
        if result.value > now + timedelta(hours=6):
            warning = "DATETIME_FUTURE_IMPOSSIBLE"
        else:
            return None
    elif not warning:
        return None
    first_seen = safe_parse_datetime(record.get("timestamp_utc"), field_name="record_timestamp", source=str(record.get("source"))).value or _parse_redacted_prefix(value)
    source_text = str(record.get("source", ""))
    row = str(record.get("row", ""))
    raw_value = str(value)
    return {
        "issue_id": _issue_id(source_text, row, field_path, raw_value),
        "field_name": field_path,
        "raw_value": raw_value,
        "source": source_text,
        "source_type": record.get("source_type"),
        "row": row,
        "event_type": record.get("event_type") or "",
        "alert_code": record.get("alert_code") or "",
        "status": _record_status(record),
        "first_seen_utc": first_seen.isoformat() if first_seen else None,
        "last_seen_utc": first_seen.isoformat() if first_seen else None,
        "warning": warning,
        "severity": _severity(field_path, record, context, first_seen),
        "affects_metrics": _affects_metrics(field_path, record),
        "affects_acceptance": True,
        "suggested_action": "Quarantine historical evidence after review; fix source if issue appears in current telemetry window.",
        "execution_attempted": False,
    }


def _severity(field_path: str, record: Mapping[str, Any], context: Mapping[str, Any], first_seen: datetime | None) -> str:
    if _is_active_record(record, context, first_seen):
        return "ERROR"
    if _affects_metrics(field_path, record):
        return "WARNING"
    return "INFO"


def _is_active_record(record: Mapping[str, Any], context: Mapping[str, Any], first_seen: datetime | None) -> bool:
    if _record_status(record).upper() == "CLOSED":
        return False
    window_start = safe_parse_datetime(context.get("latest_clean_window_start_utc"), field_name="window_start", source="telemetry_context").value
    if first_seen is not None and window_start is not None and first_seen >= window_start:
        return True
    event_type = str(record.get("event_type") or "").upper()
    source = str(record.get("source", "")).lower()
    return event_type == "HEARTBEAT" and ("heartbeats" in source or "events" in source)


def _record_status(record: Mapping[str, Any]) -> str:
    payload = record.get("payload")
    if isinstance(payload, Mapping):
        return str(payload.get("status") or "")
    return ""


def _parse_redacted_prefix(value: Any) -> datetime | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(value or ""))
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(0)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _affects_metrics(field_path: str, record: Mapping[str, Any]) -> bool:
    text = f"{field_path} {record.get('source', '')} {record.get('event_type', '')}".lower()
    return any(marker in text for marker in ("paper_trade", "trade", "heartbeat", "forward_metrics", "evidence_summary"))


def _looks_like_timestamp_field(field_path: str) -> bool:
    lowered = field_path.lower()
    if lowered.endswith("_id") or lowered.endswith(".id") or "heartbeat_id" in lowered:
        return False
    return any(marker in lowered for marker in TIMESTAMP_FIELD_MARKERS)


def _missing_timestamp_is_critical(field_path: str, record: Mapping[str, Any]) -> bool:
    lowered = field_path.lower()
    event_type = str(record.get("event_type") or "").upper()
    source = str(record.get("source", "")).lower()
    if lowered.endswith("timestamp_utc") and event_type in {"HEARTBEAT", "FORWARD_SHADOW_CYCLE", "PAPER_TRADE_OPENED", "PAPER_TRADE_CLOSED"}:
        return True
    return "heartbeats" in source and lowered.endswith("timestamp_utc")


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


def _issue_id(source: str, row: str, field_path: str, raw_value: str) -> str:
    import hashlib

    payload = f"{source}|{row}|{field_path}|{raw_value}".encode("utf-8", errors="replace")
    return "tsi_" + hashlib.sha256(payload).hexdigest()[:24]
