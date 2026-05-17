"""Threshold sweep configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from typing import Any, Iterable

from .signal_profile import SignalProfileSettings


@dataclass(frozen=True)
class ThresholdConfig:
    """One threshold combination for calibration."""

    profile: str
    min_setup_score: float
    min_component_score: float
    cost_fit_min: float
    structure_fit_min: float
    volatility_fit_min: float
    session_fit_min: float
    ensemble_min_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_threshold_grid(profiles: Iterable[SignalProfileSettings]) -> tuple[ThresholdConfig, ...]:
    """Generate a controlled threshold sweep grid."""

    rows: list[ThresholdConfig] = []
    for profile in profiles:
        for values in product(
            (50, 55, 60, 65, 70, 75),
            (40, 50, 60),
            (40, 50, 60, 70),
            (40, 50, 60, 70),
            (40, 50, 60, 70),
            (40, 50, 60, 70),
            (50, 55, 60, 65, 70),
        ):
            rows.append(ThresholdConfig(profile.name, *map(float, values)))
    return tuple(rows)


def profile_threshold(profile: SignalProfileSettings) -> ThresholdConfig:
    """Return the threshold config for a named profile."""

    return ThresholdConfig(
        profile=profile.name,
        min_setup_score=profile.min_setup_score,
        min_component_score=profile.min_component_score,
        cost_fit_min=profile.cost_fit_min,
        structure_fit_min=profile.structure_fit_min,
        volatility_fit_min=profile.volatility_fit_min,
        session_fit_min=profile.session_fit_min,
        ensemble_min_score=profile.ensemble_min_score,
    )
