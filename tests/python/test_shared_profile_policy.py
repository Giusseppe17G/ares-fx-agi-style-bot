from dataclasses import replace

import pytest

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.calibration.decision_policy import (
    COMPONENTS, evaluate_profile_thresholds, evaluate_stability_filters, resolve_signal_profile,
)
from agi_style_forex_bot_mt5.backtesting.backtester import _profile_threshold_result


def evidence():
    return {"setup_quality_score": 90, "ensemble_score": 90, "component_scores": {key: 90 for key in COMPONENTS}}


@pytest.mark.parametrize("value", [None, 0, float("nan"), float("inf"), True, "invalid", -1, 101])
def test_missing_invalid_or_low_setup_score_cannot_bypass_gate(value):
    profile = resolve_signal_profile(BotConfig())
    metadata = evidence() | {"setup_quality_score": value}
    passed, reasons = evaluate_profile_thresholds(metadata, profile)
    assert not passed and any("setup_score" in code for code in reasons)
    assert _profile_threshold_result(metadata, profile) == (passed, reasons)


@pytest.mark.parametrize("component", COMPONENTS)
def test_every_component_is_required(component):
    metadata = evidence()
    del metadata["component_scores"][component]
    assert not evaluate_profile_thresholds(metadata, resolve_signal_profile(BotConfig()))[0]


def test_profile_complete_evidence_and_inclusive_threshold():
    profile = resolve_signal_profile(BotConfig())
    metadata = evidence() | {"setup_quality_score": profile["min_setup_score"]}
    assert evaluate_profile_thresholds(metadata, profile) == (True, ())


def test_invalid_profile_and_missing_overlay_cannot_silently_fallback(tmp_path):
    with pytest.raises(ValueError):
        resolve_signal_profile(replace(BotConfig(), signal_profile="TYPO"))
    with pytest.raises(ValueError):
        resolve_signal_profile(replace(BotConfig(), profile_config=str(tmp_path / "missing.ini")))


@pytest.mark.parametrize("name", ["BALANCED_STABLE", "BALANCED_STABLE_MICRO", "BALANCED_STABLE_MICRO_V2"])
def test_stability_overlay_filters_apply_to_micro_descendants(name):
    profile = {"name": name, "apply_stability_filters": True, "disabled_symbols": ["EURUSD"]}
    assert evaluate_stability_filters(profile, symbol="eurusd", strategy_name="test", session="LONDON", regime="RANGE") == (False, "STABLE_SYMBOL_DISABLED")
