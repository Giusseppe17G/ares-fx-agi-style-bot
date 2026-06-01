"""Cooldown risk audit."""

from __future__ import annotations

from typing import Any, Mapping


def audit_cooldown_risk(extracted: Mapping[str, Any]) -> dict[str, Any]:
    return _audit_reason("COOLDOWN", extracted)


def _audit_reason(reason: str, extracted: Mapping[str, Any]) -> dict[str, Any]:
    total = int(extracted.get("risk_rejected_count", 0) or 0)
    count = 0
    for row in extracted.get("reason_breakdown", []):
        if str(row.get("risk_block_reason")) == reason:
            count = int(row.get("count", 0) or 0)
            break
    return {
        "risk_block_reason": reason,
        "count": count,
        "share": round(count / total, 4) if total else 0.0,
        "dominates": bool(total and count / total > 0.4),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
