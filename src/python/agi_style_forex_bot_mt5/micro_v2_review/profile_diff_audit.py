"""Profile diff audit for micro V2 candidates."""

from __future__ import annotations

from typing import Any, Mapping


RISK_KEYS = {"PAPER_RISK_MULTIPLIER", "RISK_MULTIPLIER", "MAX_OPEN_PAPER_TRADES", "MAX_PAPER_TRADES_PER_DAY", "MAX_OPEN_TRADES"}
COOLDOWN_KEYS = {"COOLDOWN_AFTER_LOSS_MINUTES", "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES"}
SESSION_KEYS = {"BLOCKED_SESSIONS", "ALLOWED_SESSIONS", "SESSION_FILTER", "BLOCKED_SESSIONS_STABLE"}
THRESHOLD_KEYS = {"MIN_SETUP_SCORE", "MIN_SETUP_SCORE_STABLE", "ENSEMBLE_THRESHOLD", "SIGNAL_SCORE_THRESHOLD"}
SYMBOL_KEYS = {"DISABLED_SYMBOLS", "ALLOWED_SYMBOLS", "SYMBOLS"}
PAPER_LIMIT_KEYS = {"MAX_OPEN_PAPER_TRADES", "MAX_PAPER_TRADES_PER_DAY"}


def build_profile_diff(base: Mapping[str, str], candidate: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(set(base) | set(candidate)):
        before = base.get(key)
        after = candidate.get(key)
        if before == after:
            continue
        change_type = "ADDED" if before is None else "REMOVED" if after is None else "MODIFIED"
        rows.append(
            {
                "key": key,
                "base_value": "" if before is None else before,
                "candidate_value": "" if after is None else after,
                "change_type": change_type,
                "change_category": _category(key),
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    return rows


def _category(key: str) -> str:
    upper = key.upper()
    if upper in RISK_KEYS:
        return "risk"
    if upper in COOLDOWN_KEYS:
        return "cooldown"
    if upper in SESSION_KEYS:
        return "session"
    if upper in THRESHOLD_KEYS:
        return "threshold"
    if upper in SYMBOL_KEYS:
        return "symbol_universe"
    if upper in PAPER_LIMIT_KEYS:
        return "paper_limit"
    if "LIVE" in upper or "DEMO" in upper or "ORDER" in upper:
        return "safety"
    return "metadata"
