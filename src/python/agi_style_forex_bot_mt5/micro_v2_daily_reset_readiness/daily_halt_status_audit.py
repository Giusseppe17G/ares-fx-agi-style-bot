"""Daily halt status audit for Micro V2 reset readiness.

FASE 81: this module keeps its output vocabulary (`daily_halt_active`,
`daily_reset_occurred`, ...) but no longer decides anything itself. The verdict
comes from `core.operational_state.halt_detector`, the single halt authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from agi_style_forex_bot_mt5.core import FrozenClock, SystemClock
from agi_style_forex_bot_mt5.core.operational_state import detect_halt, halt_kind_of, is_halt_event


def audit_daily_halt_status(dataset: Mapping[str, Any], *, current_utc: datetime | None = None) -> dict[str, Any]:
    clock = FrozenClock(current_utc) if current_utc is not None else SystemClock()
    assessment = detect_halt(dataset, clock=clock)
    return {
        "daily_halt_status": "DAILY_HALT_ACTIVE_CURRENT_DAY" if assessment.halt_active else "DAILY_HALT_EXPIRED_OR_NOT_FOUND",
        "daily_halt_active": assessment.halt_active,
        "daily_halt_event_count": assessment.halt_event_count,
        "latest_halt_utc": assessment.halt_timestamp_utc,
        "latest_halt_operational_day": assessment.halt_operational_day,
        "current_operational_day": assessment.current_operational_day,
        "daily_reset_occurred": assessment.daily_reset_occurred,
        "halt_reason": assessment.halt_reason,
        "halt_kind": assessment.halt_kind.value,
        "halt_age": assessment.halt_age.value,
        "evidence_quality": assessment.evidence_quality.value,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


# Kept for callers that imported these directly; both now delegate.
_is_halt_event = is_halt_event
_halt_kind_of = halt_kind_of
