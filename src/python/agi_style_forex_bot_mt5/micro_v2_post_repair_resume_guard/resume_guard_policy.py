"""Post-repair resume guard policy for isolated Micro V2."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_runtime_profile import MICRO_V2_SIGNAL_PROFILE

from .manage_open_trades_only_policy import build_manage_open_trades_only_policy


def is_v2_dryrun_sqlite(path: str | Path) -> bool:
    normalized = str(path).replace("/", "\\").lower()
    return normalized.endswith(r"data\sqlite\forward-shadow-v2-dryrun.sqlite3") or normalized.endswith("forward-shadow-v2-dryrun.sqlite3")


def evaluate_post_repair_resume_guard(
    *,
    signal_profile: str,
    sqlite_path: str | Path,
    profile_values: Mapping[str, str] | None,
    lifecycle: Mapping[str, Any],
    safety_flags: bool,
    daily_risk_status: str = "PAPER_DAILY_RISK_BLOCKED_OPEN_TRADES",
) -> dict[str, Any]:
    profile_values = profile_values or {}
    canonical = str(signal_profile or profile_values.get("SIGNAL_PROFILE") or profile_values.get("PROFILE_NAME") or "").upper()
    open_count = int(lifecycle.get("open_trade_count", 0) or 0)
    invalid_count = int(lifecycle.get("invalid_open_trade_count", 0) or 0)
    if safety_flags:
        return _result("MICRO_V2_POST_REPAIR_SAFETY_BLOCKED", False, "Safety flags detected.")
    if canonical != MICRO_V2_SIGNAL_PROFILE:
        return _result("MICRO_V2_POST_REPAIR_BLOCKED_PROFILE_MISMATCH", False, "Only BALANCED_STABLE_MICRO_V2 can use manage-open-trades-only.")
    if not is_v2_dryrun_sqlite(sqlite_path):
        return _result("MICRO_V2_POST_REPAIR_BLOCKED_SQLITE_SCOPE_MISMATCH", False, "Only isolated V2 SQLite can use this guard.")
    if invalid_count > 0:
        return _result("MICRO_V2_POST_REPAIR_BLOCKED_INVALID_OPEN_TRADES", False, "Invalid open paper trades remain.")
    if open_count <= 0:
        return _result("MICRO_V2_POST_REPAIR_BLOCKED_NO_OPEN_TRADES", False, "No open paper trades need manage-only resume.")
    if daily_risk_status != "PAPER_DAILY_RISK_BLOCKED_OPEN_TRADES":
        return _result("MICRO_V2_POST_REPAIR_RESUME_GUARD_READY", False, "Daily risk open-trade deadlock is not active.")
    policy = build_manage_open_trades_only_policy(enabled=True, reason="PAPER_DAILY_RISK_BLOCKED_OPEN_TRADES with valid V2 open trades after repair")
    return {
        "micro_v2_post_repair_resume_guard_status": "MICRO_V2_POST_REPAIR_MANAGE_OPEN_TRADES_ONLY_ENABLED",
        "accepted": True,
        "reason": policy["reason"],
        **policy,
    }


def _result(status: str, accepted: bool, reason: str) -> dict[str, Any]:
    return {
        "micro_v2_post_repair_resume_guard_status": status,
        "accepted": accepted,
        "reason": reason,
        **build_manage_open_trades_only_policy(enabled=False, reason=reason),
    }
