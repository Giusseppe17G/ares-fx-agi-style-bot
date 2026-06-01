"""Load target invalid open trades from Phase 68 reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ALLOWED_ISSUE = "ZERO_RISK_DISTANCE_ENTRY_EQUALS_SL"
ALLOWED_ACTION = "QUARANTINE_INVALID_OPEN_PAPER_TRADES"


def load_open_trade_repair_plan(drawdown_recovery_dir: str | Path) -> dict[str, Any]:
    root = Path(drawdown_recovery_dir)
    audit = _load_json(root / "open_trade_integrity_audit.json")
    summary = _load_json(root / "micro_v2_daily_drawdown_state_recovery_summary.json")
    reasons = audit.get("invalid_open_trade_reasons", [])
    reasons = reasons if isinstance(reasons, list) else []
    targets = [dict(item) for item in reasons if isinstance(item, dict) and str(item.get("reason")) == ALLOWED_ISSUE]
    errors: list[str] = []
    if summary and summary.get("drawdown_halt_root_cause") != "OPEN_TRADE_INTEGRITY_ISSUE":
        errors.append("DRAWDOWN_ROOT_CAUSE_MISMATCH")
    if not targets:
        errors.append("NO_ZERO_RISK_TARGETS")
    if len(targets) != int(audit.get("invalid_open_trade_count", len(targets)) or 0):
        errors.append("TARGET_COUNT_MISMATCH")
    if any(str(item.get("symbol", "")).upper() != "USDJPY" for item in targets):
        errors.append("SYMBOL_MISMATCH")
    return {
        "repair_action": ALLOWED_ACTION,
        "plan_valid": not errors,
        "plan_errors": errors,
        "target_trade_ids": [str(item.get("paper_trade_id") or "") for item in targets],
        "target_trades": targets,
        "drawdown_recovery_status": summary.get("micro_v2_daily_drawdown_state_recovery_status", ""),
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
