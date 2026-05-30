"""Effective profile thresholds used by research/backtest flows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .signal_profile import SignalProfileSettings, get_signal_profile


@dataclass(frozen=True)
class EffectiveProfileConfig:
    """Resolved profile thresholds and safety flags."""

    profile_name: str
    thresholds: dict[str, float]
    profile_hash: str
    allowed_for_shadow: bool
    not_for_demo_live: bool
    research_only: bool
    source: str
    filters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def effective_profile_config(profile_name: str, *, source: str = "canonical", profile_config: str | Path | None = None) -> EffectiveProfileConfig:
    """Resolve canonical thresholds and a stable hash for one profile."""

    profile = get_signal_profile(profile_name)
    thresholds = thresholds_from_profile(profile)
    filters = _stable_filters(profile.name, profile_config)
    if profile.name in {"BALANCED_STABLE", "BALANCED_STABLE_MICRO", "BALANCED_STABLE_MICRO_V2"} and filters.get("min_setup_score_stable") is not None:
        thresholds["min_setup_score"] = float(filters["min_setup_score_stable"])
    payload = {
        "profile_name": profile.name,
        "thresholds": thresholds,
        "allowed_for_shadow": _profile_allowed_for_shadow(profile),
        "not_for_demo_live": bool(profile.not_for_demo_live),
        "research_only": bool(profile.research_only),
        "filters": filters,
    }
    digest = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return EffectiveProfileConfig(
        profile_name=profile.name,
        thresholds=thresholds,
        profile_hash=digest,
        allowed_for_shadow=_profile_allowed_for_shadow(profile),
        not_for_demo_live=bool(profile.not_for_demo_live),
        research_only=bool(profile.research_only),
        source=source,
        filters=filters,
    )


def thresholds_from_profile(profile: SignalProfileSettings) -> dict[str, float]:
    """Return numeric threshold fields only."""

    return {
        "ensemble_min_score": float(profile.ensemble_min_score),
        "min_setup_score": float(profile.min_setup_score),
        "min_component_score": float(profile.min_component_score),
        "cost_fit_min": float(profile.cost_fit_min),
        "session_fit_min": float(profile.session_fit_min),
        "structure_fit_min": float(profile.structure_fit_min),
        "volatility_fit_min": float(profile.volatility_fit_min),
        "near_miss_window": float(profile.near_miss_window),
    }


def _profile_allowed_for_shadow(profile: SignalProfileSettings) -> bool:
    return profile.name in {"CONSERVATIVE", "BALANCED", "BALANCED_FILTERED"} and not bool(profile.not_for_demo_live)


def _stable_filters(profile_name: str, profile_config: str | Path | None) -> dict[str, Any]:
    if profile_name not in {"BALANCED_STABLE", "BALANCED_STABLE_MICRO", "BALANCED_STABLE_MICRO_V2"}:
        return {}
    values = _read_simple_ini(Path(profile_config)) if profile_config else {}
    return {
        "apply_stability_filters": _bool_value(values.get("APPLY_STABILITY_FILTERS", values.get("STABILITY_FILTERS_APPLIED", "false"))),
        "disabled_symbols": _csv_values(values.get("DISABLED_SYMBOLS", "")),
        "disabled_strategies": _csv_values(values.get("DISABLED_STRATEGIES", "")),
        "blocked_sessions": _csv_values(values.get("BLOCKED_SESSIONS", "")),
        "blocked_regimes": _csv_values(values.get("BLOCKED_REGIMES", "")),
        "min_setup_score_stable": _number(values.get("MIN_SETUP_SCORE_STABLE", "")),
        "profile_type": values.get("PROFILE_TYPE", "RESEARCH_BACKTEST_ONLY"),
        "requires_robustness_rerun": _bool_value(values.get("REQUIRES_ROBUSTNESS_RERUN", "true")),
        "paper_only": _bool_value(values.get("PAPER_ONLY", "false")),
        "paper_risk_multiplier": _number(values.get("PAPER_RISK_MULTIPLIER", "")),
        "max_open_paper_trades": _number(values.get("MAX_OPEN_PAPER_TRADES", "")),
        "max_paper_trades_per_day": _number(values.get("MAX_PAPER_TRADES_PER_DAY", "")),
        "cooldown_after_loss_minutes": _number(values.get("COOLDOWN_AFTER_LOSS_MINUTES", "")),
        "cooldown_after_drawdown_halt_minutes": _number(values.get("COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES", "")),
        "block_new_entries_after_daily_halt": _bool_value(values.get("BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT", "false")),
        "manual_resume_required": _bool_value(values.get("MANUAL_RESUME_REQUIRED", "false")),
    }


def _read_simple_ini(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def _csv_values(value: str) -> list[str]:
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


def _bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
