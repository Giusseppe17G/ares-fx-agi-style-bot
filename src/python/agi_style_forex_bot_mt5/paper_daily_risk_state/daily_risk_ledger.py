"""Ledger for reviewed daily paper drawdown halts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from agi_style_forex_bot_mt5.paper_risk_review.profile_matching import normalize_profile_name
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


def ledger_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "paper_daily_risk_ledger.json"


def load_daily_risk_ledger(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    ledger = Path(path)
    if not ledger.exists():
        return {}
    try:
        payload = json.loads(ledger.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def latest_daily_risk_clearance(ledger: Mapping[str, Any]) -> dict[str, Any]:
    entries = ledger.get("daily_risk_clearances", [])
    if not isinstance(entries, list) or not entries:
        return {}
    return dict(entries[-1])


def append_daily_risk_clearance(
    *,
    output_dir: str | Path,
    reason: str,
    latest_halt_utc: str,
    latest_clearance_utc: str,
    clearance_id: str,
    operational_day: str,
    reviewer: str = "operator",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = ledger_path(output)
    ledger = load_daily_risk_ledger(path) or {"mode": "paper-daily-risk-ledger", "daily_risk_clearances": []}
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "daily_risk_clearance_id": f"pdrc_{uuid4().hex}",
        "created_at_utc": now,
        "reviewer": reviewer,
        "reason": reason,
        "cleared_for_profile": "BALANCED_STABLE_MICRO",
        "canonical_cleared_for_profile": normalize_profile_name("BALANCED_STABLE_MICRO"),
        "cleared_for_paper_shadow": True,
        "not_for_demo_live": True,
        "stale_halts_cleared": True,
        "active_halts_cleared": False,
        "latest_halt_utc_at_clearance": latest_halt_utc,
        "latest_profile_clearance_utc": latest_clearance_utc,
        "profile_clearance_id": clearance_id,
        "operational_day": operational_day,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    entries = list(ledger.get("daily_risk_clearances", [])) if isinstance(ledger.get("daily_risk_clearances"), list) else []
    entries.append(entry)
    ledger = {**ledger, "daily_risk_clearances": entries, "updated_at_utc": now, "execution_attempted": False}
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")
    return {**entry, "ledger_path": str(path)}


def daily_risk_clearance_is_stale(clearance: Mapping[str, Any], latest_halt_utc: str) -> bool:
    if not clearance:
        return True
    if not latest_halt_utc:
        return False
    cleared = safe_parse_datetime(clearance.get("created_at_utc"), field_name="created_at_utc", source="paper_daily_risk")
    halt = safe_parse_datetime(latest_halt_utc, field_name="latest_halt_utc", source="paper_daily_risk")
    if cleared.value is None or halt.value is None:
        return True
    return cleared.value < halt.value
