"""Trade limit risk audits."""

from __future__ import annotations

from typing import Any, Mapping

from .cooldown_risk_audit import _audit_reason


def audit_trade_limit(extracted: Mapping[str, Any]) -> dict[str, Any]:
    return _audit_reason("MAX_PAPER_TRADES_PER_DAY", extracted)


def audit_max_open_trades(extracted: Mapping[str, Any]) -> dict[str, Any]:
    return _audit_reason("MAX_OPEN_TRADES", extracted)
