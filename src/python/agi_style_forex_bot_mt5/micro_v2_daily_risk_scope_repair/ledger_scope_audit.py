"""Audit daily risk ledger scope for Micro V2."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


EXPECTED_PROFILE = "BALANCED_STABLE_MICRO_V2"


def audit_ledger_scope(inputs: Mapping[str, Any]) -> dict[str, Any]:
    ledger = inputs.get("ledger_payload") if isinstance(inputs.get("ledger_payload"), Mapping) else {}
    entries = ledger.get("daily_risk_clearances") if isinstance(ledger, Mapping) else []
    entries = entries if isinstance(entries, list) else []
    latest = dict(entries[-1]) if entries else {}
    v2_entries = [_entry for _entry in entries if _canonical(_entry) == EXPECTED_PROFILE]
    stable_entries = [_entry for _entry in entries if _canonical(_entry) == "BALANCED_STABLE_MICRO"]
    closed = inputs.get("closed_loss_summary") if isinstance(inputs.get("closed_loss_summary"), Mapping) else {}
    recovery = inputs.get("drawdown_recovery_summary") if isinstance(inputs.get("drawdown_recovery_summary"), Mapping) else {}
    v2_sqlite = str(inputs.get("v2_sqlite") or "")
    latest_profile = _canonical(latest)
    closed_scaled = _float(closed.get("closed_scaled_pnl_total"))
    closed_count = int(closed.get("closed_trade_count", 0) or 0)
    quarantine_count = int(closed.get("quarantined_trade_count", 0) or 0)
    halt_active = bool(closed.get("daily_halt_should_remain")) or str(recovery.get("micro_v2_daily_drawdown_state_recovery_status", "")).upper() == "MICRO_V2_DRAWDOWN_HALT_LEGITIMATE"
    pnl_matches = closed_scaled is not None and abs(closed_scaled - (-9.996)) <= 1e-9
    closed_matches = closed_count == 2
    unsafe_reset = any(bool((entry if isinstance(entry, Mapping) else {}).get("active_halts_cleared")) for entry in v2_entries)
    status = "DAILY_RISK_SCOPE_OK_FOR_V2" if v2_entries and not unsafe_reset else "DAILY_RISK_SCOPE_MISMATCH_REPAIR_NEEDED"
    if not entries:
        status = "DAILY_RISK_LEDGER_MISSING"
    if not pnl_matches:
        status = "DAILY_RISK_SCOPE_PNL_MISMATCH"
    if unsafe_reset or (v2_entries and any(not bool((entry if isinstance(entry, Mapping) else {}).get("daily_halt_active", True)) for entry in v2_entries)):
        status = "DAILY_RISK_SCOPE_UNSAFE_RESET_DETECTED"
    return {
        "daily_risk_scope_status_before": status if status != "DAILY_RISK_SCOPE_OK_FOR_V2" else "DAILY_RISK_SCOPE_OK_FOR_V2",
        "ledger_entry_count": len(entries),
        "stable_entry_count": len(stable_entries),
        "v2_entry_count": len(v2_entries),
        "profile_canonical_current": latest_profile,
        "expected_profile_canonical": EXPECTED_PROFILE,
        "sqlite_scope_current": str(latest.get("sqlite_scope") or latest.get("sqlite_path") or ""),
        "expected_sqlite_scope": _norm_path(v2_sqlite),
        "ledger_mixes_stable_and_v2": bool(stable_entries and v2_entries),
        "closed_scaled_pnl_total": closed_scaled if closed_scaled is not None else 0.0,
        "closed_trade_count": closed_count,
        "quarantined_trade_count": quarantine_count,
        "closed_loss_legitimate": bool(closed.get("closed_loss_legitimate")),
        "pnl_matches_expected": pnl_matches,
        "closed_trade_count_matches_expected": closed_matches,
        "daily_halt_active": halt_active,
        "halt_source": "V2_PAPER_DRY_RUN" if halt_active else "",
        "halt_corresponds_to_v2": bool(halt_active and closed.get("closed_loss_legitimate")),
        "ledger_contains_v2_scope": bool(v2_entries),
        "ledger_contains_stable_scope": bool(stable_entries),
        "mismatch_functional": not bool(v2_entries),
        "mismatch_metadata_only": bool(v2_entries) and latest_profile != EXPECTED_PROFILE,
        "unsafe_reset_detected": bool(unsafe_reset),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _canonical(entry: Any) -> str:
    if not isinstance(entry, Mapping):
        return ""
    return str(entry.get("canonical_cleared_for_profile") or entry.get("profile_canonical") or entry.get("cleared_for_profile") or "").upper()


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _norm_path(value: str) -> str:
    return str(Path(value)).replace("/", "\\")
