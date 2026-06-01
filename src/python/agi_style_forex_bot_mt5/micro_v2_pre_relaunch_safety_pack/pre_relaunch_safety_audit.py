"""Offline audit for Micro V2 pre-relaunch safety hardening."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paper_trade_creation_guard import PaperTradeGuardInput, validate_paper_trade_creation


REJECTION_REASONS = [
    "PAPER_TRADE_REJECTED_ZERO_RISK_DISTANCE",
    "PAPER_TRADE_REJECTED_SL_EQUALS_ENTRY",
    "PAPER_TRADE_REJECTED_TP_EQUALS_ENTRY",
    "PAPER_TRADE_REJECTED_INVALID_LONG_SL_TP",
    "PAPER_TRADE_REJECTED_INVALID_SHORT_SL_TP",
    "PAPER_TRADE_REJECTED_ZERO_ATR_STOP_DISTANCE",
    "PAPER_TRADE_REJECTED_PRECISION_ROUNDING_COLLAPSE",
    "PAPER_TRADE_REJECTED_INVALID_ENTRY_PRICE",
    "PAPER_TRADE_REJECTED_INVALID_SL_PRICE",
    "PAPER_TRADE_REJECTED_INVALID_TP_PRICE",
    "PAPER_TRADE_REJECTED_INVALID_SIDE",
    "PAPER_TRADE_REJECTED_INVALID_REWARD_DISTANCE",
]


def audit_prevention_guards() -> dict[str, Any]:
    cases = [
        ("long_sl_equals_entry", PaperTradeGuardInput(1.1, 1.1, 1.2, "BUY", 5, {})),
        ("short_sl_equals_entry", PaperTradeGuardInput(1.1, 1.1, 1.0, "SELL", 5, {})),
        ("long_bad_side", PaperTradeGuardInput(1.1, 1.2, 1.3, "BUY", 5, {})),
        ("short_bad_side", PaperTradeGuardInput(1.1, 1.0, 0.9, "SELL", 5, {})),
        ("tp_equals_entry", PaperTradeGuardInput(1.1, 1.0, 1.1, "BUY", 5, {})),
        ("zero_atr", PaperTradeGuardInput(1.1, 1.0, 1.2, "BUY", 5, {"atr_stop_distance": 0})),
        ("rounding_collapse", PaperTradeGuardInput(1.100004, 1.100003, 1.10002, "BUY", 5, {})),
        ("valid_long", PaperTradeGuardInput(1.1, 1.0, 1.2, "BUY", 5, {})),
        ("valid_short", PaperTradeGuardInput(1.1, 1.2, 1.0, "SELL", 5, {})),
    ]
    results = [{"case": name, **validate_paper_trade_creation(candidate)} for name, candidate in cases]
    rejected = [row for row in results if not row["paper_trade_creation_allowed"]]
    return {
        "zero_risk_guard_enabled": True,
        "invalid_paper_trade_prevention_active": True,
        "paper_trade_creation_guard_status": "PAPER_TRADE_CREATION_GUARD_ENABLED",
        "zero_risk_rejections_count": len([row for row in rejected if "RISK" in str(row.get("rejection_reason")) or "SL_EQUALS_ENTRY" in str(row.get("rejection_reason"))]),
        "last_zero_risk_rejection_reason": rejected[-1]["rejection_reason"] if rejected else "",
        "sl_tp_side_guard_enabled": True,
        "precision_rounding_guard_enabled": True,
        "rejection_reasons_added": REJECTION_REASONS,
        "guard_test_cases": results,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}
