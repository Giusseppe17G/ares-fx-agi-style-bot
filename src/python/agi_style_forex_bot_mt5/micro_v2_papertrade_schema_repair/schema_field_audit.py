"""Audit PaperTrade schema fields and extra payload fields."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .extra_field_filter import constructor_field_names, detect_extra_fields, extra_metadata_key


WRAPPER_FIELDS = {"source", "opened_at_utc", "closed_at_utc", "execution_attempted", "order_send_called", "order_check_called"}


def audit_schema_fields(trades: list[Mapping[str, Any]], events: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    extra_counter: Counter[str] = Counter()
    trade_rows: list[dict[str, Any]] = []
    for trade in trades:
        extras = {key: value for key, value in detect_extra_fields(trade).items() if key not in WRAPPER_FIELDS}
        for key in extras:
            extra_counter[key] += 1
        if extras:
            trade_rows.append(
                {
                    "paper_trade_id": str(trade.get("paper_trade_id") or ""),
                    "status": str(trade.get("status") or ""),
                    "symbol": str(trade.get("symbol") or ""),
                    "extra_fields": sorted(extras),
                    "invalid_close": bool(extras.get("invalid_close", False) or trade.get("invalid_close", False)),
                }
            )
    event_invalid_close = 0
    for event in events or []:
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else event
        if isinstance(payload, Mapping) and ("invalid_close" in payload or "invalid_close" in str(payload)):
            event_invalid_close += 1
    return {
        "constructor_fields": constructor_field_names(),
        "extra_metadata_key": extra_metadata_key(),
        "extra_fields_detected": dict(sorted(extra_counter.items())),
        "extra_field_trade_count": len(trade_rows),
        "invalid_close_trade_count": int(extra_counter.get("invalid_close", 0)),
        "invalid_close_event_mentions": event_invalid_close,
        "trades_with_extra_fields": trade_rows,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
