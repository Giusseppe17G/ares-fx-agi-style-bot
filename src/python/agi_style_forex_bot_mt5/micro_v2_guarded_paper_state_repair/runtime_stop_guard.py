"""Runtime stop guard for guarded V2 repair."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


ACTIVE_HEARTBEAT_SECONDS = 120


def audit_runtime_stopped(v2_sqlite: str | Path, v2_log_dir: str | Path, *, now_utc: datetime | None = None) -> dict[str, Any]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    dataset = load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2")
    latest = _latest_heartbeat(dataset.get("heartbeats", []))
    age = None
    runtime_active = False
    if latest:
        parsed = safe_parse_datetime(latest, field_name="timestamp_utc", source="micro_v2_guarded_repair")
        if parsed.value is not None:
            age = max((now - parsed.value.astimezone(timezone.utc)).total_seconds(), 0.0)
            runtime_active = age <= ACTIVE_HEARTBEAT_SECONDS
    lock_files = [str(path) for path in Path(v2_log_dir).glob("*.lock")] if Path(v2_log_dir).exists() else []
    if lock_files:
        runtime_active = True
    return {
        "runtime_guard_status": "RUNTIME_ACTIVE" if runtime_active else "RUNTIME_STOPPED",
        "runtime_active": runtime_active,
        "latest_heartbeat_utc": latest,
        "heartbeat_age_seconds": round(age, 4) if age is not None else None,
        "lock_files": lock_files,
        "safety_flags_detected": _safety(dataset),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _latest_heartbeat(rows: list[Mapping[str, Any]]) -> str:
    timestamps = [str(row.get("timestamp_utc") or "") for row in rows if row.get("timestamp_utc")]
    return sorted(timestamps)[-1] if timestamps else ""


def _safety(dataset: Mapping[str, Any]) -> bool:
    for group in ("events", "heartbeats", "paper_trades"):
        for row in dataset.get(group, []):
            payload = row.get("payload", {}) if isinstance(row.get("payload"), Mapping) else {}
            if row.get("execution_attempted") or row.get("order_send_called") or row.get("order_check_called"):
                return True
            if payload.get("execution_attempted") or payload.get("order_send_called") or payload.get("order_check_called"):
                return True
    return False
