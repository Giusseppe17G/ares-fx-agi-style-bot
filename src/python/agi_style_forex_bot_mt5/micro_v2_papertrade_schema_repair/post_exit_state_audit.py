"""Post-exit V2 paper state audit."""

from __future__ import annotations

from typing import Any, Mapping


QUARANTINE_STATUS = "QUARANTINED_INVALID_PAPER_TRADE"


def audit_post_exit_state(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    open_trades = [trade for trade in trades if str(trade.get("status", "")).upper() == "OPEN"]
    closed = [trade for trade in trades if str(trade.get("status", "")).upper() == "CLOSED"]
    quarantined = [trade for trade in trades if str(trade.get("status", "")).upper() == QUARANTINE_STATUS]
    invalid_status = [trade for trade in trades if str(trade.get("status", "")).upper() not in {"OPEN", "CLOSED", QUARANTINE_STATUS}]
    ids: dict[str, int] = {}
    for trade in trades:
        trade_id = str(trade.get("paper_trade_id") or "")
        ids[trade_id] = ids.get(trade_id, 0) + 1
    duplicates = sorted(trade_id for trade_id, count in ids.items() if trade_id and count > 1)
    closed_missing_fields = [
        str(trade.get("paper_trade_id") or "")
        for trade in closed
        if not trade.get("exit_time_utc") or trade.get("exit_price") in (None, "")
    ]
    quarantined_with_close = [
        str(trade.get("paper_trade_id") or "")
        for trade in quarantined
        if trade.get("exit_time_utc") or str(trade.get("exit_reason") or "").upper() == "CLOSED"
    ]
    artificial_pnl = [
        str(trade.get("paper_trade_id") or "")
        for trade in quarantined
        if _float(trade.get("profit")) not in (None, 0.0) or _float(trade.get("scaled_paper_pnl")) not in (None, 0.0)
    ]
    corrupt = bool(invalid_status or duplicates or closed_missing_fields or quarantined_with_close or artificial_pnl)
    return {
        "post_exit_state_status": "MICRO_V2_PAPERTRADE_SCHEMA_POST_EXIT_STATE_CORRUPT" if corrupt else "MICRO_V2_PAPERTRADE_SCHEMA_POST_EXIT_STATE_HEALTHY",
        "open_trade_count": len(open_trades),
        "closed_trade_count": len(closed),
        "quarantined_trade_count": len(quarantined),
        "invalid_status_count": len(invalid_status),
        "duplicate_trade_ids": duplicates,
        "closed_missing_exit_fields": closed_missing_fields,
        "quarantined_with_close_fields": quarantined_with_close,
        "quarantined_with_artificial_pnl": artificial_pnl,
        "open_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in open_trades],
        "closed_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in closed],
        "quarantined_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in quarantined],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None
