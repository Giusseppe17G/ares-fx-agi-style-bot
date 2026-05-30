"""Central rejection event taxonomy for market-data and symbol guards."""

from __future__ import annotations

from typing import Any, Mapping


NEW_REJECTION_EVENTS = {
    "STALE_TICK_REJECTION",
    "MARKET_CLOSED_REJECTION",
    "FUTURE_SIGNAL_REJECTION",
    "INVALID_MARKET_SNAPSHOT_REJECTION",
}


def classify_rejection_event_type(
    *,
    reject_code: str | None = None,
    reject_reason: str | None = None,
    payload: Mapping[str, Any] | None = None,
    fallback: str = "SYMBOL_REJECTED",
) -> str:
    """Return a precise rejection event type without weakening fail-closed behavior."""

    data = dict(payload or {})
    code = str(reject_code or data.get("reject_code") or "").upper()
    reason = str(reject_reason or data.get("reject_reason") or data.get("reason") or "").lower()
    tick_status = str(data.get("tick_time_status") or "").upper()
    normalization_reason = str(data.get("normalization_reason") or "").lower()
    market_closed = bool(data.get("market_is_probably_closed", False))
    if market_closed or code == "MARKET_CLOSED_OR_NO_TICKS":
        return "MARKET_CLOSED_REJECTION"
    if tick_status in {"FUTURE_TOO_FAR"} or "future" in reason or "future" in normalization_reason:
        return "FUTURE_SIGNAL_REJECTION"
    if tick_status in {"STALE", "NORMALIZED_STALE"} or "stale" in reason or "stale" in normalization_reason:
        return "STALE_TICK_REJECTION"
    if code in {"MARKET_DATA_INVALID", "MARKET_DATA_REJECTED"} or tick_status == "INVALID_TIMESTAMP" or "snapshot" in reason:
        return "INVALID_MARKET_SNAPSHOT_REJECTION"
    return fallback


def is_suspected_misclassified_symbol_rejection(event_type: str, payload: Mapping[str, Any] | None = None, message: str | None = None) -> bool:
    """Return true when a legacy SYMBOL_REJECTED payload contains non-symbol rejection evidence."""

    if str(event_type).upper() != "SYMBOL_REJECTED":
        return False
    precise = classify_rejection_event_type(payload=payload or {}, reject_reason=message, fallback="SYMBOL_REJECTED")
    return precise != "SYMBOL_REJECTED"
