"""Precision rounding collapse validation."""

from __future__ import annotations


def validate_precision_rounding(*, entry_price: float, sl_price: float, tp_price: float, digits: int | None) -> str:
    if digits is None:
        return ""
    rounded_entry = round(entry_price, int(digits))
    rounded_sl = round(sl_price, int(digits))
    rounded_tp = round(tp_price, int(digits))
    if abs(rounded_entry - rounded_sl) <= 0:
        return "PAPER_TRADE_REJECTED_PRECISION_ROUNDING_COLLAPSE"
    if abs(rounded_tp - rounded_entry) <= 0:
        return "PAPER_TRADE_REJECTED_PRECISION_ROUNDING_COLLAPSE"
    return ""
