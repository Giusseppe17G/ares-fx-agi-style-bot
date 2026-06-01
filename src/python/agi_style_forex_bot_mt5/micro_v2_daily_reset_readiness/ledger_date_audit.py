"""Daily risk ledger date/scope audit for Micro V2 reset readiness."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


EXPECTED_PROFILE = "BALANCED_STABLE_MICRO_V2"


def audit_ledger_date(inputs: Mapping[str, Any], *, current_utc: datetime | None = None) -> dict[str, Any]:
    now = current_utc or datetime.now(timezone.utc)
    ledger = inputs.get("ledger_payload") if isinstance(inputs.get("ledger_payload"), Mapping) else {}
    entries = ledger.get("daily_risk_clearances") if isinstance(ledger.get("daily_risk_clearances"), list) else []
    v2_entries = [entry for entry in entries if isinstance(entry, Mapping) and _canonical(entry) == EXPECTED_PROFILE]
    latest = dict(v2_entries[-1]) if v2_entries else {}
    created = _parse_ts(latest.get("created_at_utc"))
    operational_day = str(latest.get("operational_day") or (created.date().isoformat() if created else ""))
    expected_sqlite = str(Path(str(inputs.get("v2_sqlite") or ""))).replace("/", "\\")
    sqlite_scope = str(latest.get("sqlite_scope") or "")
    closed_scaled = _float(latest.get("closed_scaled_pnl_total"))
    scope_ok = bool(
        latest
        and _canonical(latest) == EXPECTED_PROFILE
        and sqlite_scope == expected_sqlite
        and bool(latest.get("daily_halt_active", False))
        and closed_scaled is not None
        and abs(closed_scaled - (-9.996)) <= 1e-9
        and int(latest.get("closed_trade_count", 0) or 0) == 2
    )
    return {
        "ledger_date_status": "DAILY_RISK_SCOPE_OK_FOR_V2" if scope_ok else "DAILY_RISK_SCOPE_INVALID",
        "daily_risk_scope_status": "DAILY_RISK_SCOPE_OK_FOR_V2" if scope_ok else "DAILY_RISK_SCOPE_INVALID",
        "ledger_entry_count": len(entries),
        "v2_ledger_entry_count": len(v2_entries),
        "latest_v2_ledger_created_at_utc": latest.get("created_at_utc", ""),
        "latest_v2_operational_day": operational_day,
        "current_operational_day": now.date().isoformat(),
        "ledger_date_is_current": operational_day == now.date().isoformat(),
        "ledger_date_is_prior": bool(operational_day and operational_day < now.date().isoformat()),
        "profile_canonical": _canonical(latest),
        "expected_profile_canonical": EXPECTED_PROFILE,
        "sqlite_scope": sqlite_scope,
        "expected_sqlite_scope": expected_sqlite,
        "daily_halt_active_in_ledger": bool(latest.get("daily_halt_active", False)),
        "closed_scaled_pnl_total": closed_scaled if closed_scaled is not None else 0.0,
        "closed_trade_count": int(latest.get("closed_trade_count", 0) or 0),
        "quarantined_trade_count": int(latest.get("quarantined_trade_count", 0) or 0),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _canonical(entry: Mapping[str, Any]) -> str:
    return str(entry.get("canonical_cleared_for_profile") or entry.get("profile_canonical") or entry.get("cleared_for_profile") or "").upper()


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None
