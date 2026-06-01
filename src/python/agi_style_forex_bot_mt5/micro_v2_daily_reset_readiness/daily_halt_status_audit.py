"""Daily halt status audit for Micro V2 reset readiness."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def audit_daily_halt_status(dataset: Mapping[str, Any], *, current_utc: datetime | None = None) -> dict[str, Any]:
    now = current_utc or datetime.now(timezone.utc)
    halts = [_halt_event(event) for event in dataset.get("events", []) if _is_halt_event(event)]
    latest = halts[-1] if halts else {}
    latest_ts = _parse_ts(latest.get("timestamp_utc"))
    latest_day = latest_ts.date().isoformat() if latest_ts else ""
    current_day = now.date().isoformat()
    halt_active_current_day = bool(latest_ts and latest_ts.date() >= now.date())
    return {
        "daily_halt_status": "DAILY_HALT_ACTIVE_CURRENT_DAY" if halt_active_current_day else "DAILY_HALT_EXPIRED_OR_NOT_FOUND",
        "daily_halt_active": halt_active_current_day,
        "daily_halt_event_count": len(halts),
        "latest_halt_utc": latest.get("timestamp_utc", ""),
        "latest_halt_operational_day": latest_day,
        "current_operational_day": current_day,
        "daily_reset_occurred": bool(latest_ts and latest_ts.date() < now.date()),
        "halt_reason": latest.get("halt_reason", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _is_halt_event(event: Mapping[str, Any]) -> bool:
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    text = " ".join(str(item) for item in (event.get("event_type"), event.get("message"), payload.get("halt_reason"), payload.get("alert_code")))
    return "PAPER_DAILY_DRAWDOWN" in text or "PAPER_DAILY_DRAWDOWN_HALT" in text


def _halt_event(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    return {
        "timestamp_utc": str(event.get("timestamp_utc") or payload.get("timestamp_utc") or ""),
        "halt_reason": str(payload.get("halt_reason") or payload.get("alert_code") or event.get("message") or ""),
        "event_type": str(event.get("event_type") or ""),
    }


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None
