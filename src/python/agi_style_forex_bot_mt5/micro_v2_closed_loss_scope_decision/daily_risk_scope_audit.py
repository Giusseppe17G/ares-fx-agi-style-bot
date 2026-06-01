"""Daily risk ledger scope audit for Micro V2."""

from __future__ import annotations

from typing import Any, Mapping


def audit_daily_risk_scope(ledger: Mapping[str, Any], *, requested_profile: str = "BALANCED_STABLE_MICRO_V2", closed_scaled_pnl_total: float = 0.0) -> dict[str, Any]:
    entries = ledger.get("daily_risk_clearances") if isinstance(ledger, Mapping) else []
    entries = entries if isinstance(entries, list) else []
    latest = dict(entries[-1]) if entries else {}
    cleared = str(latest.get("canonical_cleared_for_profile") or latest.get("cleared_for_profile") or "").upper()
    requested = requested_profile.upper()
    scope_mismatch = bool(latest and cleared and cleared != requested)
    contains_v2 = any(str((entry if isinstance(entry, Mapping) else {}).get("canonical_cleared_for_profile") or "").upper() == requested for entry in entries)
    if not latest:
        status = "DAILY_RISK_SCOPE_LEDGER_MISSING"
    elif scope_mismatch and closed_scaled_pnl_total < 0:
        status = "DAILY_RISK_SCOPE_MISMATCH_REPAIR_NEEDED"
    elif scope_mismatch:
        status = "DAILY_RISK_SCOPE_MISMATCH_METADATA_ONLY"
    else:
        status = "DAILY_RISK_SCOPE_VALID"
    return {
        "daily_risk_scope_status": status,
        "daily_risk_ledger_entry_count": len(entries),
        "requested_profile_canonical": requested,
        "ledger_cleared_for_profile_canonical": cleared,
        "ledger_scope_mismatch": scope_mismatch,
        "ledger_contains_v2_scope": contains_v2,
        "latest_daily_risk_clearance_id": latest.get("daily_risk_clearance_id", ""),
        "latest_daily_risk_created_at_utc": latest.get("created_at_utc", ""),
        "ledger_shared_with_base": scope_mismatch and cleared == "BALANCED_STABLE_MICRO",
        "ledger_may_affect_runtime_restart": scope_mismatch,
        "closed_scaled_pnl_total_in_scope": closed_scaled_pnl_total,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
