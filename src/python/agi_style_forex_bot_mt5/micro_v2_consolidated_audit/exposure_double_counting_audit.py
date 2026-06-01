"""Exposure double-counting checks."""

from __future__ import annotations

from typing import Any, Mapping


def audit_exposure_double_counting(exposure: Mapping[str, Any]) -> dict[str, Any]:
    detected = (
        int(exposure.get("exposure_block_count", 0) or 0) > 0
        and int(exposure.get("paper_trades_open", 0) or 0) == 0
        and bool(exposure.get("exposure_actual_zero", False))
    )
    return {
        "double_counting_detected": detected,
        "data_missing_detected": bool(exposure.get("exposure_data_missing", False)),
        "profile_parse_error": bool(exposure.get("profile_parse_error", False)),
        "diagnosis": "POSSIBLE_DOUBLE_COUNTING" if detected else str(exposure.get("exposure_guard_diagnosis", "")),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
