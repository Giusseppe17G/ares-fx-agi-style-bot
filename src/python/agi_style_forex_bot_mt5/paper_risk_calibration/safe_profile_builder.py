"""Build BALANCED_STABLE_MICRO paper-only profile artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .paper_risk_budget import micro_risk_budget


def build_safe_paper_profile(
    *,
    base_profile: str = "BALANCED_STABLE",
    risk_audit_dir: str | Path = "data/reports/paper_risk",
    output_dir: str | Path = "data/reports/paper_risk",
) -> dict[str, Any]:
    """Create a safe paper-only profile overlay without changing global defaults."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    audit = _load_json(Path(risk_audit_dir) / "paper_risk_summary.json")
    budget = micro_risk_budget()
    budget["base_profile"] = base_profile.upper()
    budget["source_risk_classification"] = audit.get("classification", audit.get("paper_risk_status", ""))
    ini_path = output / "balanced_stable_micro.ini"
    json_path = output / "balanced_stable_micro.json"
    ini_path.write_text(_ini_text(budget), encoding="utf-8")
    json_path.write_text(json.dumps({**budget, "execution_attempted": False}, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "mode": "build-paper-risk-profile",
        "profile": "BALANCED_STABLE_MICRO",
        "base_profile": budget["base_profile"],
        "profile_config": str(ini_path),
        "json_config": str(json_path),
        "not_for_demo_live": True,
        "paper_only": True,
        "allowed_for_shadow": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "reports_created": [str(ini_path), str(json_path)],
    }


def _ini_text(values: Mapping[str, Any]) -> str:
    mapping = {
        "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO",
        "BASE_PROFILE": values.get("base_profile", "BALANCED_STABLE"),
        "NOT_FOR_DEMO_LIVE": "true",
        "PAPER_ONLY": "true",
        "ALLOWED_FOR_SHADOW": "true",
        "PROFILE_TYPE": values.get("profile_type", "PAPER_SHADOW_ONLY"),
        "REQUIRE_STABLE_GATE": "true",
        "REQUIRE_PROFILE_CONFIG": "true",
        "REDUCED_PAPER_SIZE": "true",
        "PAPER_RISK_MULTIPLIER": values.get("paper_risk_multiplier", 0.10),
        "MAX_OPEN_PAPER_TRADES": values.get("max_open_paper_trades", 1),
        "MAX_PAPER_TRADES_PER_DAY": values.get("max_paper_trades_per_day", 2),
        "COOLDOWN_AFTER_LOSS_MINUTES": values.get("cooldown_after_loss_minutes", 120),
        "COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES": values.get("cooldown_after_drawdown_halt_minutes", 1440),
        "BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT": "true",
        "MANUAL_RESUME_REQUIRED": "true",
        "STABILITY_FILTERS_APPLIED": "true",
        "RISK_PROFILE_USED": "BALANCED_STABLE_MICRO",
    }
    return "\n".join(f"{key}={value}" for key, value in mapping.items()) + "\n"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
