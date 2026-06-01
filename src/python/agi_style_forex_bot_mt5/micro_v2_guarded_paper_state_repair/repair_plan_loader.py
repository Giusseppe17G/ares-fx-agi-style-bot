"""Repair plan loading and guard validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ALLOWED_ACTION = "QUARANTINE_INVALID_PAPER_TRADE"


def load_repair_plan(path: str | Path) -> dict[str, Any]:
    plan_path = Path(path)
    if not plan_path.exists():
        return {"plan_valid": False, "plan_error": "REPAIR_PLAN_MISSING", "path": str(plan_path)}
    try:
        loaded = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"plan_valid": False, "plan_error": f"REPAIR_PLAN_PARSE_ERROR: {exc}", "path": str(plan_path)}
    if not isinstance(loaded, dict):
        return {"plan_valid": False, "plan_error": "REPAIR_PLAN_NOT_OBJECT", "path": str(plan_path)}
    validation = validate_repair_plan(loaded)
    return {**loaded, **validation, "path": str(plan_path)}


def validate_repair_plan(plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if plan.get("repair_action_recommended") != ALLOWED_ACTION:
        errors.append("UNSAFE_REPAIR_ACTION")
    for key in ("NOT_APPLIED", "PAPER_ONLY", "REQUIRES_BACKUP", "REQUIRES_RUNTIME_STOP", "REQUIRES_EXPLICIT_NEXT_PHASE"):
        if plan.get(key) is not True:
            errors.append(f"{key}_NOT_TRUE")
    for key in ("APPROVED_FOR_RUNTIME", "APPROVED_FOR_DEMO", "APPROVED_FOR_LIVE"):
        if plan.get(key) is not False:
            errors.append(f"{key}_NOT_FALSE")
    if plan.get("root_cause") != "SL_EQUALS_ENTRY":
        errors.append("ROOT_CAUSE_MISMATCH")
    targets = plan.get("target_trade_ids")
    if not isinstance(targets, list) or not targets:
        errors.append("TARGET_TRADE_IDS_MISSING")
    return {"plan_valid": not errors, "plan_errors": errors, "plan_error": ";".join(errors)}
