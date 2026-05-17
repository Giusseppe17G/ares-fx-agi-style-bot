"""Signal frequency profiles for research-only calibration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class SignalProfile(str, Enum):
    """Supported signal frequency profiles."""

    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    BALANCED_FILTERED = "BALANCED_FILTERED"
    ACTIVE = "ACTIVE"
    RESEARCH_ONLY = "RESEARCH_ONLY"


@dataclass(frozen=True)
class SignalProfileSettings:
    """Thresholds used by calibration reports."""

    name: str
    min_setup_score: float
    min_component_score: float
    cost_fit_min: float
    structure_fit_min: float
    volatility_fit_min: float
    session_fit_min: float
    ensemble_min_score: float
    near_miss_window: float
    research_only: bool = False
    not_for_demo_live: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILES: dict[str, SignalProfileSettings] = {
    "CONSERVATIVE": SignalProfileSettings("CONSERVATIVE", 72, 60, 70, 65, 65, 60, 70, 5),
    "BALANCED": SignalProfileSettings("BALANCED", 62, 50, 55, 50, 50, 50, 60, 8),
    "BALANCED_FILTERED": SignalProfileSettings("BALANCED_FILTERED", 62, 50, 55, 50, 50, 50, 60, 8),
    "ACTIVE": SignalProfileSettings("ACTIVE", 52, 40, 45, 40, 40, 40, 50, 12, research_only=True, not_for_demo_live=True),
    "RESEARCH_ONLY": SignalProfileSettings("RESEARCH_ONLY", 45, 30, 35, 30, 30, 30, 40, 20, research_only=True, not_for_demo_live=True),
}


def get_signal_profile(name: str | SignalProfile) -> SignalProfileSettings:
    """Return a profile or raise on invalid input."""

    key = str(name.value if isinstance(name, SignalProfile) else name).strip().upper()
    if key not in PROFILES:
        raise ValueError("SIGNAL_PROFILE must be CONSERVATIVE, BALANCED, BALANCED_FILTERED, ACTIVE, or RESEARCH_ONLY")
    return PROFILES[key]


def parse_profiles(value: str | tuple[str, ...] | list[str] | None) -> tuple[SignalProfileSettings, ...]:
    """Parse comma-separated profile names."""

    if value is None:
        return (PROFILES["CONSERVATIVE"], PROFILES["BALANCED"], PROFILES["ACTIVE"], PROFILES["RESEARCH_ONLY"])
    parts = value.split(",") if isinstance(value, str) else list(value)
    return tuple(get_signal_profile(part) for part in parts if str(part).strip())
