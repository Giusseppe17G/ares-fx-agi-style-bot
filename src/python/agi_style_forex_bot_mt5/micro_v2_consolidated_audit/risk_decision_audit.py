"""Risk decision audit for Micro V2 consolidated report."""

from __future__ import annotations

from typing import Any, Mapping


def audit_risk_decision(risk_block: Mapping[str, Any], exposure: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "micro_v2_risk_block_status": risk_block.get("micro_v2_risk_block_status", ""),
        "dominant_risk_block_reason": risk_block.get("dominant_risk_block_reason", ""),
        "dominant_risk_block_share": risk_block.get("dominant_risk_block_share", 0.0),
        "risk_rejected_count": risk_block.get("risk_rejected_count", 0),
        "exposure_guard_diagnosis": exposure.get("exposure_guard_diagnosis", ""),
        "affected_symbols": risk_block.get("affected_symbols", exposure.get("affected_symbols", [])),
        "risk_guard_expected": exposure.get("exposure_guard_diagnosis") == "EXPOSURE_GUARD_EXPECTED"
        or risk_block.get("micro_v2_risk_block_status") == "MICRO_V2_RISK_BLOCK_EXPECTED_SAFETY_GUARD",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
