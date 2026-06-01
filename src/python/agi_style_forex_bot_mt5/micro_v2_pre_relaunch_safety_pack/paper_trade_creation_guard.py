"""Prevent invalid paper trades before PaperTrade construction or SQLite insert."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .precision_rounding_validator import validate_precision_rounding
from .sl_tp_side_validator import normalize_side, validate_sl_tp_side
from .stop_distance_validator import validate_stop_distances
from .zero_risk_guard import zero_risk_reason


@dataclass(frozen=True)
class PaperTradeGuardInput:
    entry_price: float | None
    sl_price: float | None
    tp_price: float | None
    side: str
    digits: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def validate_paper_trade_creation(candidate: PaperTradeGuardInput) -> dict[str, Any]:
    reason = zero_risk_reason(entry_price=candidate.entry_price, sl_price=candidate.sl_price, tp_price=candidate.tp_price)
    if reason:
        return _result(False, reason, candidate)
    entry = float(candidate.entry_price or 0.0)
    sl = float(candidate.sl_price or 0.0)
    tp = float(candidate.tp_price or 0.0)
    for validator_reason in (
        validate_sl_tp_side(side=candidate.side, entry_price=entry, sl_price=sl, tp_price=tp),
        validate_stop_distances(entry_price=entry, sl_price=sl, tp_price=tp, metadata=candidate.metadata),
        validate_precision_rounding(entry_price=entry, sl_price=sl, tp_price=tp, digits=candidate.digits),
    ):
        if validator_reason:
            return _result(False, validator_reason, candidate)
    return _result(True, "", candidate)


def _result(allowed: bool, reason: str, candidate: PaperTradeGuardInput) -> dict[str, Any]:
    entry = float(candidate.entry_price or 0.0)
    sl = float(candidate.sl_price or 0.0)
    tp = float(candidate.tp_price or 0.0)
    return {
        "paper_trade_creation_allowed": allowed,
        "paper_trade_creation_guard_status": "PAPER_TRADE_CREATION_GUARD_PASS" if allowed else "PAPER_TRADE_CREATION_GUARD_REJECTED",
        "rejection_reason": reason,
        "normalized_side": normalize_side(candidate.side),
        "entry_price": candidate.entry_price,
        "sl_price": candidate.sl_price,
        "tp_price": candidate.tp_price,
        "digits": candidate.digits,
        "risk_distance": abs(entry - sl) if entry and sl else 0.0,
        "reward_distance": abs(tp - entry) if tp and entry else 0.0,
        "zero_risk_guard_enabled": True,
        "invalid_paper_trade_prevention_active": True,
        "sl_tp_side_guard_enabled": True,
        "precision_rounding_guard_enabled": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
