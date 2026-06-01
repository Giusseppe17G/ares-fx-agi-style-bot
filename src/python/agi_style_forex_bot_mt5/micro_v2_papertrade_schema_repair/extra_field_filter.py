"""PaperTrade extra-field filtering helpers."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.paper_trading.paper_trade import (
    EXTRA_FIELDS_METADATA_KEY,
    paper_trade_constructor_fields,
    paper_trade_extra_fields,
    sanitize_paper_trade_payload,
)


def filter_extra_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return sanitize_paper_trade_payload(payload)


def detect_extra_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return paper_trade_extra_fields(payload)


def constructor_field_names() -> list[str]:
    return sorted(paper_trade_constructor_fields())


def extra_metadata_key() -> str:
    return EXTRA_FIELDS_METADATA_KEY
