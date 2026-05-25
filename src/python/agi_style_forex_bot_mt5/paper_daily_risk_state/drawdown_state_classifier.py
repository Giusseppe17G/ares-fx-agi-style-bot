"""Classify paper drawdown halt events relative to clearance state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime

from .daily_risk_ledger import daily_risk_clearance_is_stale, latest_daily_risk_clearance, load_daily_risk_ledger
from .daily_window import current_operational_day, operational_day


def classify_drawdown_halts(
    *,
    halt_events: list[Mapping[str, Any]],
    profile_clearance: Mapping[str, Any],
    daily_risk_ledger: str | None = None,
    now: datetime | None = None,
    profile_config: str | None = None,
) -> dict[str, Any]:
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = current_operational_day(now_utc, profile_config)
    profile_clearance_time = safe_parse_datetime(profile_clearance.get("created_at_utc"), field_name="created_at_utc", source="paper_daily_risk")
    ledger = load_daily_risk_ledger(daily_risk_ledger)
    daily_clearance = latest_daily_risk_clearance(ledger)
    daily_clearance_time = safe_parse_datetime(daily_clearance.get("created_at_utc"), field_name="created_at_utc", source="paper_daily_risk")
    rows: list[dict[str, Any]] = []
    latest_halt_utc = ""
    for index, event in enumerate(halt_events):
        raw_ts = event.get("timestamp_utc")
        parsed = safe_parse_datetime(raw_ts, field_name="timestamp_utc", source=str(event.get("source", "paper_daily_risk")))
        event_day = operational_day(raw_ts, profile_config)
        classification = "UNKNOWN_HALT_REVIEW_REQUIRED"
        if parsed.value is None:
            classification = "INVALID_TIMESTAMP_HALT"
        elif daily_clearance_time.value is not None and parsed.value <= daily_clearance_time.value:
            classification = "HISTORICAL_REVIEWED_HALT"
        elif profile_clearance_time.value is not None and parsed.value <= profile_clearance_time.value:
            classification = "STALE_HALT_BEFORE_CLEARANCE"
        elif event_day == today:
            classification = "ACTIVE_TODAY_HALT"
        elif profile_clearance_time.value is not None and parsed.value > profile_clearance_time.value:
            classification = "ACTIVE_TODAY_HALT"
        row = {
            "halt_index": index,
            "source": event.get("source", ""),
            "halt_code": event.get("halt_code", ""),
            "timestamp_utc": parsed.value.isoformat() if parsed.value is not None else str(raw_ts or ""),
            "timestamp_parse_status": parsed.status,
            "operational_day": event_day,
            "classification": classification,
            "execution_attempted": False,
        }
        rows.append(row)
        if parsed.value is not None and (not latest_halt_utc or parsed.value.isoformat() > latest_halt_utc):
            latest_halt_utc = parsed.value.isoformat()
    active_count = sum(1 for row in rows if row["classification"] == "ACTIVE_TODAY_HALT")
    stale_count = sum(1 for row in rows if row["classification"] == "STALE_HALT_BEFORE_CLEARANCE")
    invalid_count = sum(1 for row in rows if row["classification"] == "INVALID_TIMESTAMP_HALT")
    unknown_count = sum(1 for row in rows if row["classification"] == "UNKNOWN_HALT_REVIEW_REQUIRED")
    historical_reviewed = sum(1 for row in rows if row["classification"] == "HISTORICAL_REVIEWED_HALT")
    latest_after_clearance = _latest_after(profile_clearance_time.value, latest_halt_utc)
    ledger_stale = daily_risk_clearance_is_stale(daily_clearance, latest_halt_utc) if daily_clearance else True
    return {
        "halt_classifications": rows,
        "active_today_halt_count": active_count,
        "stale_halt_count": stale_count,
        "invalid_timestamp_halt_count": invalid_count,
        "unknown_halt_count": unknown_count,
        "historical_reviewed_halt_count": historical_reviewed,
        "latest_clearance_utc": profile_clearance_time.value.isoformat() if profile_clearance_time.value else "",
        "latest_halt_utc": latest_halt_utc,
        "latest_halt_after_clearance": latest_after_clearance,
        "daily_risk_ledger_status": "DAILY_RISK_LEDGER_ACCEPTED" if daily_clearance and not ledger_stale else ("DAILY_RISK_LEDGER_STALE" if daily_clearance else "DAILY_RISK_LEDGER_MISSING"),
        "daily_risk_clearance": daily_clearance,
        "daily_risk_clearance_id": daily_clearance.get("daily_risk_clearance_id", "") if daily_clearance else "",
        "daily_risk_ledger_stale": ledger_stale,
        "operational_day": today,
        "execution_attempted": False,
    }


def _latest_after(clearance_dt: datetime | None, latest_halt_utc: str) -> bool:
    if clearance_dt is None or not latest_halt_utc:
        return bool(latest_halt_utc)
    parsed = safe_parse_datetime(latest_halt_utc, field_name="latest_halt_utc", source="paper_daily_risk")
    return bool(parsed.value is not None and parsed.value > clearance_dt)
