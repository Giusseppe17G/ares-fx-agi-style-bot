"""Invalid paper trade and sizing risk audits."""

from __future__ import annotations

from typing import Any, Mapping

from .cooldown_risk_audit import _audit_reason


def audit_invalid_trade_state(extracted: Mapping[str, Any]) -> dict[str, Any]:
    invalid_state = _audit_reason("INVALID_TRADE_STATE", extracted)
    invalid_distance = _audit_reason("INVALID_RISK_DISTANCE", extracted)
    zero_size = _audit_reason("ZERO_POSITION_SIZE", extracted)
    invalid_sl_tp = _audit_reason("INVALID_SL_TP", extracted)
    return {
        "invalid_trade_state": invalid_state,
        "invalid_risk_distance": invalid_distance,
        "zero_position_size": zero_size,
        "invalid_sl_tp": invalid_sl_tp,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
