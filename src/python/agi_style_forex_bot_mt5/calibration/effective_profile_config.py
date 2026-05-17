"""Effective profile thresholds used by research/backtest flows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def effective_profile_config(profile_name: str, *, source: str = "canonical") -> EffectiveProfileConfig:
    """Resolve canonical thresholds and a stable hash for one profile."""

    profile = get_signal_profile(profile_name)
    thresholds = thresholds_from_profile(profile)
    payload = {
        "profile_name": profile.name,
        "thresholds": thresholds,
        "allowed_for_shadow": _profile_allowed_for_shadow(profile),
        "not_for_demo_live": bool(profile.not_for_demo_live),
        "research_only": bool(profile.research_only),
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
