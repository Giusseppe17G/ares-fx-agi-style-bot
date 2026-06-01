"""Audit PaperTrade loader compatibility."""

from __future__ import annotations

import json
from typing import Any, Mapping

from agi_style_forex_bot_mt5.paper_trading.paper_trade import EXTRA_FIELDS_METADATA_KEY, PaperTrade


def audit_papertrade_loader(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    preserved_count = 0
    loaded_count = 0
    for trade in trades:
        try:
            loaded = PaperTrade.from_mapping(trade)
            loaded_count += 1
            metadata = dict(loaded.metadata)
            extras = metadata.get(EXTRA_FIELDS_METADATA_KEY)
            if isinstance(extras, Mapping) and extras:
                preserved_count += 1
        except Exception as exc:  # pragma: no cover - report path
            errors.append(
                {
                    "paper_trade_id": str(trade.get("paper_trade_id") or ""),
                    "status": str(trade.get("status") or ""),
                    "error": str(exc),
                }
            )
    json_errors: list[dict[str, Any]] = []
    for trade in trades:
        try:
            PaperTrade.from_json(json.dumps(dict(trade), sort_keys=True))
        except Exception as exc:  # pragma: no cover - report path
            json_errors.append(
                {
                    "paper_trade_id": str(trade.get("paper_trade_id") or ""),
                    "status": str(trade.get("status") or ""),
                    "error": str(exc),
                }
            )
    return {
        "papertrade_rows_checked": len(trades),
        "papertrade_rows_loaded": loaded_count,
        "loader_error_count": len(errors),
        "json_loader_error_count": len(json_errors),
        "extra_fields_preserved_in_metadata_count": preserved_count,
        "invalid_close_handled": not errors and not json_errors,
        "loader_errors": errors,
        "json_loader_errors": json_errors,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
