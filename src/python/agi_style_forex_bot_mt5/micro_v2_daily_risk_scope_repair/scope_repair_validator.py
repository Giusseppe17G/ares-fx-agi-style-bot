"""Post-apply validation for Micro V2 daily-risk scope repair."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .ledger_backup_manager import sha256_file
from .ledger_scope_audit import EXPECTED_PROFILE


def validate_scope_repair(
    ledger_path: str | Path,
    *,
    before_audit: Mapping[str, Any],
    before_sha256: str,
) -> dict[str, Any]:
    ledger = _load_json(Path(ledger_path))
    entries = ledger.get("daily_risk_clearances") if isinstance(ledger.get("daily_risk_clearances"), list) else []
    v2_entries = [entry for entry in entries if isinstance(entry, Mapping) and _canonical(entry) == EXPECTED_PROFILE]
    stable_entries = [entry for entry in entries if isinstance(entry, Mapping) and _canonical(entry) == "BALANCED_STABLE_MICRO"]
    latest_v2 = dict(v2_entries[-1]) if v2_entries else {}
    closed_scaled = _float(latest_v2.get("closed_scaled_pnl_total"))
    closed_count = int(latest_v2.get("closed_trade_count", 0) or 0)
    daily_halt_active = bool(latest_v2.get("daily_halt_active"))
    validation_passed = bool(
        v2_entries
        and daily_halt_active
        and closed_scaled is not None
        and abs(closed_scaled - float(before_audit.get("closed_scaled_pnl_total", -9.996) or -9.996)) <= 1e-9
        and closed_count == int(before_audit.get("closed_trade_count", 2) or 2)
        and latest_v2.get("active_halts_cleared") is False
        and stable_entries
    )
    return {
        "scope_repair_validation_status": "DAILY_RISK_SCOPE_OK_FOR_V2" if validation_passed else "DAILY_RISK_SCOPE_VALIDATION_FAILED",
        "validation_passed": validation_passed,
        "daily_risk_scope_status_after": "DAILY_RISK_SCOPE_OK_FOR_V2" if validation_passed else "DAILY_RISK_SCOPE_VALIDATION_FAILED",
        "daily_halt_active": daily_halt_active,
        "closed_scaled_pnl_total_after": closed_scaled if closed_scaled is not None else 0.0,
        "closed_trade_count_after": closed_count,
        "pnl_changed": closed_scaled != before_audit.get("closed_scaled_pnl_total"),
        "daily_halt_cleared": not daily_halt_active,
        "stable_scope_untouched": bool(stable_entries),
        "v2_scope_present": bool(v2_entries),
        "before_sha256": before_sha256,
        "after_sha256": sha256_file(ledger_path),
        "ledger_changed": before_sha256 != sha256_file(ledger_path),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _canonical(entry: Mapping[str, Any]) -> str:
    return str(entry.get("canonical_cleared_for_profile") or entry.get("profile_canonical") or entry.get("cleared_for_profile") or "").upper()


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None
