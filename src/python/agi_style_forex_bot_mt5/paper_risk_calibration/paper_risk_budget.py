"""Conservative paper-only budgets for safer shadow observation."""

from __future__ import annotations

from typing import Any


def micro_risk_budget() -> dict[str, Any]:
    """Return fail-closed defaults for BALANCED_STABLE_MICRO."""

    return {
        "profile": "BALANCED_STABLE_MICRO",
        "base_profile": "BALANCED_STABLE",
        "not_for_demo_live": True,
        "paper_only": True,
        "allowed_for_shadow": True,
        "require_stable_gate": True,
        "require_profile_config": True,
        "reduced_paper_size": True,
        "paper_risk_multiplier": 0.10,
        "max_open_paper_trades": 1,
        "max_paper_trades_per_day": 2,
        "cooldown_after_loss_minutes": 120,
        "cooldown_after_drawdown_halt_minutes": 1440,
        "block_new_entries_after_daily_halt": True,
        "manual_resume_required": True,
        "profile_type": "PAPER_SHADOW_ONLY",
    }
