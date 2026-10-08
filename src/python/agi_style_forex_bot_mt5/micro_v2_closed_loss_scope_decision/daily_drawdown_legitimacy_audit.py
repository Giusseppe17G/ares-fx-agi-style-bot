"""Daily drawdown halt legitimacy audit."""

from __future__ import annotations

from typing import Any, Mapping
from agi_style_forex_bot_mt5.core.operational_state import HaltKind, halt_kind_of


def audit_daily_drawdown_legitimacy(attribution: Mapping[str, Any], quarantine: Mapping[str, Any], dataset: Mapping[str, Any]) -> dict[str, Any]:
    halt_count = _halt_count(dataset)
    total = float(attribution.get("closed_scaled_pnl_total", 0.0) or 0.0)
    legitimate = bool(attribution.get("closed_loss_legitimate")) and halt_count > 0 and total < 0 and not quarantine.get("quarantined_contamination_detected")
    return {
        "daily_drawdown_legitimacy_status": "DAILY_DRAWDOWN_HALT_LEGITIMATE" if legitimate else "DAILY_DRAWDOWN_HALT_REVIEW_REQUIRED",
        "closed_loss_legitimate": legitimate,
        "paper_daily_drawdown_halt_detected": halt_count > 0,
        "drawdown_halt_event_count": halt_count,
        "closed_scaled_pnl_total": total,
        "quarantine_contamination_detected": bool(quarantine.get("quarantined_contamination_detected", False)),
        "keep_daily_halt": legitimate,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _halt_count(dataset: Mapping[str, Any]) -> int:
    """Count drawdown halt events using the canonical detector's token rule."""

    return sum(
        1
        for event in dataset.get("events", [])
        if isinstance(event, Mapping) and halt_kind_of(event) is HaltKind.DAILY_DRAWDOWN
    )
