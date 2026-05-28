"""Classify paper drawdown halt events relative to clearance state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime

from .daily_risk_ledger import daily_risk_clearance_is_stale, latest_daily_risk_clearance, load_daily_risk_ledger
from .daily_window import current_operational_day, operational_day
from .legacy_drawdown_quarantine import ACTIVE, classify_legacy_drawdown_events


def classify_drawdown_halts(
    *,
    halt_events: list[Mapping[str, Any]],
    profile_clearance: Mapping[str, Any],
    daily_risk_ledger: str | None = None,
    now: datetime | None = None,
    profile_config: str | None = None,
    pnl_audit_dir: str | None = None,
) -> dict[str, Any]:
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = current_operational_day(now_utc, profile_config)
    profile_clearance_time = safe_parse_datetime(profile_clearance.get("created_at_utc"), field_name="created_at_utc", source="paper_daily_risk")
    ledger = load_daily_risk_ledger(daily_risk_ledger)
    daily_clearance = latest_daily_risk_clearance(ledger)
    daily_clearance_time = safe_parse_datetime(daily_clearance.get("created_at_utc"), field_name="created_at_utc", source="paper_daily_risk")
    legacy = classify_legacy_drawdown_events(
        halt_events=halt_events,
        daily_risk_ledger=daily_risk_ledger,
        pnl_audit_dir=pnl_audit_dir or "data/reports/paper_pnl_audit",
        profile_clearance=profile_clearance,
    )
    legacy_by_index = {int(row.get("event_index", -1)): row for row in legacy.get("events", [])}
    rows: list[dict[str, Any]] = []
    latest_halt_utc = ""
    for index, event in enumerate(halt_events):
        raw_ts = event.get("timestamp_utc")
        parsed = safe_parse_datetime(raw_ts, field_name="timestamp_utc", source=str(event.get("source", "paper_daily_risk")))
        event_day = operational_day(raw_ts, profile_config)
        classification = "UNKNOWN_HALT_REVIEW_REQUIRED"
        if parsed.value is None:
            classification = "INVALID_TIMESTAMP_HALT"
        elif legacy.get("current_engine_multiplier_ready") and index in legacy_by_index and legacy_by_index[index].get("classification") != ACTIVE:
            classification = str(legacy_by_index[index].get("classification"))
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
    active_count = sum(1 for row in rows if row["classification"] in {"ACTIVE_TODAY_HALT", ACTIVE})
    stale_count = sum(1 for row in rows if row["classification"] in {"STALE_HALT_BEFORE_CLEARANCE", "LEGACY_BEFORE_CLEARANCE", "LEGACY_BEFORE_DAILY_RISK_LEDGER", "LEGACY_UNSCALED_BEFORE_PNL_FIX"})
    invalid_count = sum(1 for row in rows if row["classification"] in {"INVALID_TIMESTAMP_HALT", "INVALID_TIMESTAMP_LEGACY"})
    unknown_count = sum(1 for row in rows if row["classification"] == "UNKNOWN_HALT_REVIEW_REQUIRED")
    historical_reviewed = sum(1 for row in rows if row["classification"] == "HISTORICAL_REVIEWED_HALT")
    latest_after_clearance = _latest_after(profile_clearance_time.value, latest_halt_utc)
    ledger_stale = daily_risk_clearance_is_stale(daily_clearance, latest_halt_utc) if daily_clearance else True
    if daily_clearance and legacy.get("legacy_drawdown_quarantined") and not active_count and not unknown_count:
        ledger_stale = False
    return {
        "halt_classifications": rows,
        "active_today_halt_count": active_count,
        "stale_halt_count": stale_count,
        "invalid_timestamp_halt_count": invalid_count,
        "unknown_halt_count": unknown_count,
        "historical_reviewed_halt_count": historical_reviewed,
        "legacy_quarantined_halt_count": legacy.get("legacy_quarantined_halt_count", 0),
        "legacy_drawdown_quarantined": legacy.get("legacy_drawdown_quarantined", False),
        "active_scaled_drawdown_count": legacy.get("active_scaled_events_count", 0),
        "unknown_review_required_count": legacy.get("unknown_review_required_count", unknown_count),
        "drawdown_basis": legacy.get("drawdown_basis", "SCALED_PAPER_PNL_ONLY"),
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
