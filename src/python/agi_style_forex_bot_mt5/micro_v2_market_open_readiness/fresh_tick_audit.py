"""Fresh/stale tick audit by symbol."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


FRESH_STATUSES = {"FRESH", "NORMALIZED_FRESH"}
STALE_STATUSES = {"STALE", "NORMALIZED_STALE"}


def audit_fresh_ticks(dataset: Mapping[str, Any], *, now_utc: datetime | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    latest: dict[str, dict[str, Any]] = {}
    for event in dataset.get("events", []):
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        symbol = str(event.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "").upper()
        if not symbol:
            continue
        tick_status = str(payload.get("tick_time_status") or "").upper()
        tick_time = payload.get("selected_tick_time_utc") or payload.get("normalized_tick_utc") or payload.get("tick_time_msc_utc") or payload.get("tick_time_utc")
        tick_age = _float(payload.get("tick_age_seconds"))
        if not tick_status and tick_time in (None, "") and tick_age is None:
            continue
        event_time = _parse_time(event.get("timestamp_utc")) or _parse_time(tick_time) or now
        row = {
            "symbol": symbol,
            "latest_event_utc": event_time.isoformat(),
            "tick_time_status": tick_status,
            "tick_age_seconds": tick_age,
            "fresh_tick": tick_status in FRESH_STATUSES and (tick_age is None or abs(tick_age) <= int(payload.get("max_tick_age_seconds", 5) or 5)),
            "stale_tick": tick_status in STALE_STATUSES,
            "market_is_probably_closed": bool(payload.get("market_is_probably_closed", False)),
            "source_event_type": event.get("event_type", ""),
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
        previous = latest.get(symbol)
        if previous is None or str(row["latest_event_utc"]) >= str(previous.get("latest_event_utc", "")):
            latest[symbol] = row
    rows = sorted(latest.values(), key=lambda item: item["symbol"])
    fresh_symbols = [row["symbol"] for row in rows if row["fresh_tick"]]
    stale_symbols = [row["symbol"] for row in rows if row["stale_tick"]]
    closed_symbols = [row["symbol"] for row in rows if row["market_is_probably_closed"]]
    return rows, {
        "fresh_tick_symbols": fresh_symbols,
        "stale_tick_symbols": stale_symbols,
        "market_closed_symbols": closed_symbols,
        "fresh_tick_count": len(fresh_symbols),
        "stale_tick_symbol_count": len(stale_symbols),
        "symbols_with_tick_evidence": [row["symbol"] for row in rows],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _parse_time(value: Any) -> datetime | None:
    parsed = safe_parse_datetime(value, field_name="timestamp_utc", source="micro_v2_market_open_readiness")
    return parsed.value.astimezone(timezone.utc) if parsed.value is not None else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None
