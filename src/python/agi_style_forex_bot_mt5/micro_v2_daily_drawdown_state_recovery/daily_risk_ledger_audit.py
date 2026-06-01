"""Daily risk ledger scope/staleness audit for V2."""

from __future__ import annotations

from typing import Any, Mapping


def audit_daily_risk_ledger(ledger: Mapping[str, Any], *, requested_profile: str = "BALANCED_STABLE_MICRO_V2") -> dict[str, Any]:
    entries = ledger.get("daily_risk_clearances") if isinstance(ledger, Mapping) else []
    entries = entries if isinstance(entries, list) else []
    latest = dict(entries[-1]) if entries else {}
    cleared = str(latest.get("canonical_cleared_for_profile") or latest.get("cleared_for_profile") or "").upper()
    requested = requested_profile.upper()
    scope_mismatch = bool(latest and cleared and cleared != requested)
    status = "DAILY_RISK_LEDGER_SCOPE_MISMATCH" if scope_mismatch else "DAILY_RISK_LEDGER_ACCEPTED_FOR_V2" if latest else "DAILY_RISK_LEDGER_MISSING"
    return {
        "daily_risk_ledger_status": status,
        "daily_risk_ledger_entry_count": len(entries),
        "latest_daily_risk_clearance_id": latest.get("daily_risk_clearance_id", ""),
        "latest_daily_risk_created_at_utc": latest.get("created_at_utc", ""),
        "requested_profile_canonical": requested,
        "ledger_cleared_for_profile_canonical": cleared,
        "ledger_scope_mismatch": scope_mismatch,
        "ledger_stale": False,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
