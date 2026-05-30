"""Read-only dataset loader for micro frequency calibration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def load_frequency_dataset(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    profile_config: str | Path | None = None,
) -> dict[str, Any]:
    reports = Path(reports_root)
    profile_path = Path(profile_config) if profile_config else None
    return {
        "log_dir": str(log_dir),
        "reports_root": str(reports),
        "events": [_event_row(row) for row in database.fetch_all("events")],
        "heartbeats": [_heartbeat_row(row) for row in database.fetch_all("heartbeats")],
        "paper_trades": [_paper_trade_row(row) for row in database.fetch_paper_trades()],
        "forward_sufficiency": _load_json(reports / "forward_sufficiency" / "forward_sufficiency_summary.json"),
        "forward_evidence": _load_json(reports / "forward_evidence" / "evidence_summary.json"),
        "paper_risk": _load_json(reports / "paper_risk" / "paper_risk_status.json"),
        "profile_config_path": str(profile_path) if profile_path else "",
        "profile_config": _parse_profile_config(profile_path) if profile_path else {},
        "profile_config_lines": profile_path.read_text(encoding="utf-8").splitlines() if profile_path and profile_path.exists() else [],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _event_row(row: Any) -> dict[str, Any]:
    payload = _loads(row["payload_json"])
    return {
        "source": "sqlite:events",
        "event_type": row["event_type"],
        "symbol": row["symbol"],
        "timestamp_utc": row["timestamp_utc"],
        "severity": row["severity"],
        "message": row["message"],
        "payload": payload,
    }


def _heartbeat_row(row: Any) -> dict[str, Any]:
    return {
        "source": "sqlite:heartbeats",
        "event_type": "HEARTBEAT",
        "symbol": "",
        "timestamp_utc": row["timestamp_utc"],
        "payload": _loads(row["payload_json"]),
    }


def _paper_trade_row(row: Any) -> dict[str, Any]:
    payload = _loads(row["payload_json"])
    return {
        **payload,
        "source": "sqlite:paper_trades",
        "paper_trade_id": payload.get("paper_trade_id") or row["paper_trade_id"],
        "symbol": payload.get("symbol") or row["symbol"],
        "status": payload.get("status") or row["status"],
        "opened_at_utc": payload.get("entry_time_utc") or row["opened_at_utc"],
        "closed_at_utc": payload.get("exit_time_utc") or row["closed_at_utc"],
    }


def event_reason(event: Mapping[str, Any]) -> str:
    payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
    reasons = payload.get("blocking_reasons")
    if isinstance(reasons, list) and reasons:
        return str(reasons[0])
    return str(payload.get("reject_reason") or payload.get("reject_code") or payload.get("blocking_reason") or payload.get("reason") or event.get("message") or event.get("event_type") or "UNKNOWN")


def event_strategy(event: Mapping[str, Any]) -> str:
    payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
    return str(payload.get("strategy_name") or payload.get("strategy") or payload.get("strategy_id") or "UNKNOWN")


def event_session(event: Mapping[str, Any]) -> str:
    payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
    return str(payload.get("session") or "UNKNOWN")


def _parse_profile_config(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}
