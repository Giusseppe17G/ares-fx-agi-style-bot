"""Broker symbol mapping and stale tick diagnostics."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .symbol_normalization_audit import normalize_symbol


def audit_broker_symbol_mapping(rejections: list[Mapping[str, Any]]) -> dict[str, Any]:
    suffix_count = 0
    stale_tick_count = 0
    market_closed_count = 0
    tick_status_counter: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for event in rejections:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        canonical = str(payload.get("canonical_symbol") or event.get("symbol") or "")
        broker = str(payload.get("broker_symbol") or event.get("symbol") or "")
        tick_status = str(payload.get("tick_time_status") or "").upper()
        if tick_status:
            tick_status_counter[tick_status] += 1
        if broker and canonical and normalize_symbol(broker) == normalize_symbol(canonical) and broker.upper() != canonical.upper():
            suffix_count += 1
        if tick_status == "STALE" or "stale" in str(payload.get("normalization_reason", "")).lower():
            stale_tick_count += 1
        if bool(payload.get("market_is_probably_closed", False)):
            market_closed_count += 1
        if len(examples) < 5:
            examples.append(
                {
                    "symbol": event.get("symbol") or payload.get("symbol"),
                    "canonical_symbol": canonical,
                    "broker_symbol": broker,
                    "tick_time_status": tick_status,
                    "tick_age_seconds": payload.get("tick_age_seconds"),
                    "market_is_probably_closed": payload.get("market_is_probably_closed", False),
                    "normalization_reason": payload.get("normalization_reason", ""),
                }
            )
    if stale_tick_count:
        status = "STALE_TICK_REJECTION_MISCLASSIFIED_AS_SYMBOL_REJECTED"
    elif suffix_count:
        status = "BROKER_SUFFIX_MISMATCH"
    else:
        status = "BROKER_SYMBOL_MAPPING_OK_OR_INCONCLUSIVE"
    return {
        "broker_symbol_mapping_status": status,
        "broker_suffix_mismatch_count": suffix_count,
        "stale_tick_rejection_count": stale_tick_count,
        "market_probably_closed_count": market_closed_count,
        "tick_time_status_counts": [{"tick_time_status": key, "count": value} for key, value in tick_status_counter.most_common()],
        "broker_mapping_examples": examples,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
