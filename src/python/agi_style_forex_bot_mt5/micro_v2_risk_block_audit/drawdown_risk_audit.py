"""Drawdown risk audit."""

from __future__ import annotations

from typing import Any, Mapping

from .cooldown_risk_audit import _audit_reason


def audit_drawdown_risk(extracted: Mapping[str, Any]) -> dict[str, Any]:
    return _audit_reason("DRAWDOWN_HALT", extracted)


def audit_daily_ledger(extracted: Mapping[str, Any]) -> dict[str, Any]:
    return _audit_reason("DAILY_LEDGER_BLOCK", extracted)
