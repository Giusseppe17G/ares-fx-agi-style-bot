"""Lifecycle recheck after invalid trade quarantine."""

from __future__ import annotations

import json
from typing import Any, Mapping


ACTIVE_OPEN_STATUSES = {"OPEN", "ACTIVE"}
QUARANTINED_STATUS = "QUARANTINED_INVALID_PAPER_TRADE"


def recheck_lifecycle(dataset: Mapping[str, Any], repair_after: Mapping[str, Any] | None = None) -> dict[str, Any]:
    open_trades = [trade for trade in dataset.get("paper_trades", []) if str(trade.get("status", "")).upper() in ACTIVE_OPEN_STATUSES]
    quarantined = [trade for trade in dataset.get("paper_trades", []) if str(trade.get("status", "")).upper() == QUARANTINED_STATUS]
    invalid = [trade for trade in open_trades if _invalid_open_trade(trade)]
    closed = [trade for trade in dataset.get("paper_trades", []) if str(trade.get("status", "")).upper() == "CLOSED"]
    repair_after = repair_after or {}
    return {
        "open_trade_count": len(open_trades),
        "closed_trade_count": len(closed),
        "quarantined_trade_count": len(quarantined) or int(repair_after.get("quarantined_trade_count", 0) or 0),
        "invalid_open_trade_count": len(invalid),
        "open_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in open_trades],
        "invalid_open_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in invalid],
        "quarantined_trade_ids": [str(trade.get("paper_trade_id") or "") for trade in quarantined],
        "post_repair_invalid_clear": len(invalid) == 0,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def safety_flags(dataset: Mapping[str, Any]) -> bool:
    for group in ("events", "heartbeats", "paper_trades"):
        for row in dataset.get(group, []):
            payload = row.get("payload", {}) if isinstance(row.get("payload"), Mapping) else {}
            if row.get("execution_attempted") or row.get("order_send_called") or row.get("order_check_called"):
                return True
            if payload.get("execution_attempted") or payload.get("order_send_called") or payload.get("order_check_called"):
                return True
    return False


def _invalid_open_trade(trade: Mapping[str, Any]) -> bool:
    payload = dict(trade)
    if isinstance(trade.get("payload"), Mapping):
        payload.update(trade["payload"])
    elif isinstance(trade.get("payload_json"), str):
        try:
            loaded = json.loads(str(trade.get("payload_json")))
            if isinstance(loaded, dict):
                payload.update(loaded)
        except Exception:
            pass
    entry = _float(payload.get("entry_price") or payload.get("open_price") or payload.get("price"))
    sl = _float(payload.get("sl_price") or payload.get("stop_loss") or payload.get("sl"))
    tp = _float(payload.get("tp_price") or payload.get("take_profit") or payload.get("tp"))
    return entry is None or sl is None or tp is None or abs(entry - sl) <= 1e-12 or abs(tp - entry) <= 1e-12


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None
