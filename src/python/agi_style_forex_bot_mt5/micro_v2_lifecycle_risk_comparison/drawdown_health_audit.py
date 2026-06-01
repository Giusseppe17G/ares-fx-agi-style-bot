"""Drawdown health audit for Micro V2 paper/shadow."""

from __future__ import annotations

from typing import Any, Mapping


DRAWNDOWN_MARKERS = {
    "PAPER_DAILY_DRAWDOWN_HALT",
    "ACTIVE_SCALED_DRAWDOWN_BLOCK",
    "PAPER_DRAWDOWN_HALT_BLOCK",
}


def audit_drawdown_health(dataset: Mapping[str, Any], consolidated: Mapping[str, Any], stable_window: Mapping[str, Any]) -> dict[str, Any]:
    active_scaled = 0
    daily_halt = False
    events: list[dict[str, Any]] = []
    for event in dataset.get("events", []):
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        event_type = str(event.get("event_type") or payload.get("event_type") or "").upper()
        reason = str(payload.get("blocking_reason") or payload.get("reason") or event.get("message") or "").upper()
        if event_type in DRAWNDOWN_MARKERS or any(marker in reason for marker in DRAWNDOWN_MARKERS):
            daily_halt = True
            if event_type == "ACTIVE_SCALED_DRAWDOWN_BLOCK" or "ACTIVE_SCALED" in reason:
                active_scaled += 1
            events.append({"event_type": event_type, "symbol": event.get("symbol", ""), "timestamp_utc": event.get("timestamp_utc", ""), "reason": reason})
    active_scaled += _int(consolidated.get("active_scaled_drawdown_count"))
    active_scaled += _int(stable_window.get("active_scaled_drawdown_count"))
    daily_halt = daily_halt or str(consolidated.get("daily_drawdown_status", "")).upper() == "HALTED"
    status = "DRAWDOWN_HEALTH_BLOCKED" if active_scaled > 0 or daily_halt else "DRAWDOWN_HEALTH_OK"
    return {
        "drawdown_health_status": status,
        "active_scaled_drawdown_count": active_scaled,
        "daily_halt_active": daily_halt,
        "drawdown_current_v2": _float(consolidated.get("drawdown_current_v2"), _float(stable_window.get("drawdown_current_v2"))),
        "drawdown_events": events,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default
