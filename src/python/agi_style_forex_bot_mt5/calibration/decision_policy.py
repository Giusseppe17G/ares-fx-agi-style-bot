"""One fail-closed profile policy for historical and forward decisions."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

from .effective_profile_config import effective_profile_config


COMPONENTS = ("regime_fit", "momentum_fit", "structure_fit", "volatility_fit", "session_fit", "cost_fit", "liquidity_fit", "risk_reward_fit", "broker_fit", "portfolio_fit")


def resolve_signal_profile(config: Any) -> dict[str, Any]:
    overlay = config.profile_config
    if overlay and not Path(overlay).is_file():
        raise ValueError("configured profile overlay is missing")
    effective = effective_profile_config(config.signal_profile, source="shared-decision-policy", profile_config=overlay or None)
    return {
        "name": effective.profile_name, **effective.thresholds, **effective.filters,
        "research_only": effective.research_only,
        "not_for_demo_live": effective.not_for_demo_live,
        "allowed_for_shadow": effective.allowed_for_shadow,
        "profile_hash": effective.profile_hash, "source": effective.source,
    }


def _score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 100 else None


def evaluate_profile_thresholds(metadata: Mapping[str, Any], profile: Mapping[str, Any], *, ensemble_score: float | None = None) -> tuple[bool, tuple[str, ...]]:
    """Require complete finite evidence; zero is a score, never a missing gate."""
    failures: list[str] = []
    checks = (
        ("ensemble_score", ensemble_score if ensemble_score is not None else metadata.get("ensemble_score", metadata.get("score")), "ensemble_min_score"),
        ("setup_score", metadata.get("setup_quality_score"), "min_setup_score"),
    )
    for label, value, threshold_name in checks:
        score, threshold = _score(value), _score(profile.get(threshold_name))
        if threshold is None:
            failures.append(f"{threshold_name}_invalid")
        if score is None:
            failures.append(f"{label}_missing_or_invalid")
        elif threshold is not None and score < threshold:
            failures.append(f"{label}_below_min")
    raw = metadata.get("component_scores")
    components = raw if isinstance(raw, Mapping) else {}
    component_min = _score(profile.get("min_component_score"))
    if component_min is None:
        failures.append("min_component_score_invalid")
    for name in COMPONENTS:
        score = _score(components.get(name))
        if score is None:
            failures.append(f"{name}_missing_or_invalid")
        elif component_min is not None and score < component_min:
            failures.append("component_score_below_min")
        threshold_name = f"{name}_min"
        if name in {"cost_fit", "structure_fit", "volatility_fit", "session_fit"}:
            threshold = _score(profile.get(threshold_name))
            if threshold is None:
                failures.append(f"{threshold_name}_invalid")
            elif score is not None and score < threshold:
                failures.append(f"{name}_below_min")
    # Unknown supplied components must not smuggle NaN past the minimum gate.
    if any(_score(value) is None for value in components.values()):
        failures.append("component_score_invalid")
    return not failures, tuple(dict.fromkeys(failures))


def evaluate_stability_filters(profile: Mapping[str, Any], *, symbol: str, strategy_name: str, session: str, regime: str) -> tuple[bool, str]:
    if not profile.get("apply_stability_filters"):
        return True, ""
    for value, key, reason in (
        (symbol, "disabled_symbols", "STABLE_SYMBOL_DISABLED"),
        (strategy_name, "disabled_strategies", "STABLE_STRATEGY_DISABLED"),
        (session, "blocked_sessions", "STABLE_SESSION_BLOCK"),
        (regime, "blocked_regimes", "STABLE_REGIME_BLOCK"),
    ):
        if not value:
            return False, "STABLE_CONTEXT_MISSING"
        if value.upper() in {str(item).upper() for item in profile.get(key, ())}:
            return False, reason
    return True, ""
