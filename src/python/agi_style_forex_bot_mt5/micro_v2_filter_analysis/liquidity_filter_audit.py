"""Liquidity filter audit."""

from __future__ import annotations

from typing import Any, Mapping

from .regime_filter_audit import _audit_filter


def audit_liquidity_filter(breakdown: Mapping[str, Any]) -> dict[str, Any]:
    return _audit_filter("LIQUIDITY_BLOCK", breakdown)
