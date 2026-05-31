"""Regime filter audit."""

from __future__ import annotations

from typing import Any, Mapping


def audit_regime_filter(breakdown: Mapping[str, Any]) -> dict[str, Any]:
    return _audit_filter("REGIME_BLOCK", breakdown)


def _audit_filter(name: str, breakdown: Mapping[str, Any]) -> dict[str, Any]:
    by_filter = {str(row.get("filter_category")): row for row in breakdown.get("by_filter", [])}
    row = by_filter.get(name, {})
    real_total = int(breakdown.get("real_filter_rejections", 0) or 0)
    count = int(row.get("count", 0) or 0)
    return {
        "filter_category": name,
        "count": count,
        "real_filter_share": round(count / real_total, 4) if real_total else 0.0,
        "dominates_real_filters": bool(real_total and count / real_total > 0.4),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
