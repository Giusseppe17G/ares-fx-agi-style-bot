"""Apply the Micro V2 daily-risk ledger scope repair."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def apply_scope_repair(ledger_path: str | Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(ledger_path)
    if not bool(plan.get("repair_allowed")):
        return _result(False, "REPAIR_NOT_ALLOWED", {})
    planned = plan.get("planned_entry") if isinstance(plan.get("planned_entry"), Mapping) else {}
    if not planned:
        return _result(False, "PLANNED_ENTRY_MISSING", {})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _result(False, "LEDGER_PAYLOAD_NOT_OBJECT", {})
    except Exception as exc:
        return _result(False, f"LEDGER_READ_FAILED:{exc}", {})
    entries = payload.get("daily_risk_clearances")
    if not isinstance(entries, list):
        entries = []
    entry = dict(planned)
    payload["daily_risk_clearances"] = [*entries, entry]
    payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["execution_attempted"] = False
    payload["order_send_called"] = False
    payload["order_check_called"] = False
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return _result(True, "SCOPE_REPAIR_APPLIED", entry)


def _result(applied: bool, reason: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "repair_applied": applied,
        "apply_status": "SCOPE_REPAIR_APPLIED" if applied else "SCOPE_REPAIR_NOT_APPLIED",
        "apply_reason": reason,
        "applied_entry_id": entry.get("daily_risk_clearance_id", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
