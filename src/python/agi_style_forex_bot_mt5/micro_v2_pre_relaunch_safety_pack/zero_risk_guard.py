"""Zero-risk distance guard for paper trade creation."""

from __future__ import annotations


def zero_risk_reason(*, entry_price: float | None, sl_price: float | None, tp_price: float | None) -> str:
    if entry_price is None or entry_price <= 0:
        return "PAPER_TRADE_REJECTED_INVALID_ENTRY_PRICE"
    if sl_price is None or sl_price <= 0:
        return "PAPER_TRADE_REJECTED_INVALID_SL_PRICE"
    if tp_price is None or tp_price <= 0:
        return "PAPER_TRADE_REJECTED_INVALID_TP_PRICE"
    if abs(entry_price - sl_price) <= 1e-12:
        return "PAPER_TRADE_REJECTED_SL_EQUALS_ENTRY"
    if abs(tp_price - entry_price) <= 1e-12:
        return "PAPER_TRADE_REJECTED_TP_EQUALS_ENTRY"
    if abs(entry_price - sl_price) <= 0:
        return "PAPER_TRADE_REJECTED_ZERO_RISK_DISTANCE"
    if abs(tp_price - entry_price) <= 0:
        return "PAPER_TRADE_REJECTED_INVALID_REWARD_DISTANCE"
    return ""
