"""Paper risk acceptance helpers."""

from __future__ import annotations

from typing import Any, Mapping


def paper_risk_acceptance_clear(status: Mapping[str, Any]) -> bool:
    """Return True when paper risk does not block a new observation window."""

    return bool(status.get("can_open_new_paper_trade", False)) and str(status.get("paper_risk_status", "")).upper() != "PAPER_RISK_BLOCKED"
