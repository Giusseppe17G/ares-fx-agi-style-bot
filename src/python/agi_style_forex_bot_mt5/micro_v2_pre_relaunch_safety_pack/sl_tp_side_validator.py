"""SL/TP side validation for paper trades."""

from __future__ import annotations


BUY_SIDES = {"BUY", "LONG"}
SELL_SIDES = {"SELL", "SHORT"}


def normalize_side(value: object) -> str:
    side = str(value or "").upper()
    if side in BUY_SIDES:
        return "BUY"
    if side in SELL_SIDES:
        return "SELL"
    return ""


def validate_sl_tp_side(*, side: object, entry_price: float, sl_price: float, tp_price: float) -> str:
    normalized = normalize_side(side)
    if not normalized:
        return "PAPER_TRADE_REJECTED_INVALID_SIDE"
    if normalized == "BUY" and not (sl_price < entry_price < tp_price):
        return "PAPER_TRADE_REJECTED_INVALID_LONG_SL_TP"
    if normalized == "SELL" and not (tp_price < entry_price < sl_price):
        return "PAPER_TRADE_REJECTED_INVALID_SHORT_SL_TP"
    return ""
