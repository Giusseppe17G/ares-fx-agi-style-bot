"""PaperTrade legacy schema adapter."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.paper_trading.paper_trade import EXTRA_FIELDS_METADATA_KEY, paper_trade_extra_fields, sanitize_paper_trade_payload


LEGACY_FIELD_NAMES = {
    "invalid_close",
    "invalid_entry",
    "malformed_close_reason",
    "legacy_risk_flags",
}


def normalize_paper_trade_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return sanitize_paper_trade_payload(payload)


def incompatible_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return paper_trade_extra_fields(payload)


def legacy_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    extras = incompatible_fields(payload)
    return {key: value for key, value in extras.items() if key in LEGACY_FIELD_NAMES}


def unknown_field_quarantine_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    extras = incompatible_fields(payload)
    legacy = legacy_fields(payload)
    return {
        "unknown_field_count": len(extras),
        "unknown_fields": sorted(extras),
        "legacy_fields": sorted(legacy),
        "metadata_key": EXTRA_FIELDS_METADATA_KEY,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
