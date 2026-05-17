"""Signal frequency calibration tools."""

from .effective_profile_config import EffectiveProfileConfig, effective_profile_config
from .signal_profile import SignalProfile, SignalProfileSettings, get_signal_profile, parse_profiles
from .threshold_config import ThresholdConfig, generate_threshold_grid, profile_threshold

_LAZY_EXPORTS = {
    "analyze_blocking_reasons": (".blocking_reason_analyzer", "analyze_blocking_reasons"),
    "analyze_signal_frequency": (".signal_frequency_analyzer", "analyze_signal_frequency"),
    "apply_signal_profile": (".profile_application", "apply_signal_profile"),
    "bot_config_with_signal_profile": (".profile_application", "bot_config_with_signal_profile"),
    "is_near_miss": (".signal_frequency_analyzer", "is_near_miss"),
    "load_strategy_diagnostics": (".blocking_reason_analyzer", "load_strategy_diagnostics"),
    "profile_allowed_for_shadow": (".profile_application", "profile_allowed_for_shadow"),
    "profile_trade_frequency_status": (".profile_application", "profile_trade_frequency_status"),
    "run_blocking_reasons_report": (".calibration_report", "run_blocking_reasons_report"),
    "run_profile_comparison": (".profile_application", "run_profile_comparison"),
    "run_signal_calibration": (".calibration_report", "run_signal_calibration"),
    "run_threshold_sweep_report": (".calibration_report", "run_threshold_sweep_report"),
    "write_profile_comparison": (".profile_application", "write_profile_comparison"),
}


def __getattr__(name: str):
    """Load report/backtest-dependent helpers only when explicitly requested."""

    if name in _LAZY_EXPORTS:
        from importlib import import_module

        module_name, attr = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name, __name__), attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "SignalProfile",
    "SignalProfileSettings",
    "EffectiveProfileConfig",
    "ThresholdConfig",
    "analyze_blocking_reasons",
    "analyze_signal_frequency",
    "apply_signal_profile",
    "bot_config_with_signal_profile",
    "generate_threshold_grid",
    "effective_profile_config",
    "get_signal_profile",
    "is_near_miss",
    "load_strategy_diagnostics",
    "parse_profiles",
    "profile_allowed_for_shadow",
    "profile_trade_frequency_status",
    "profile_threshold",
    "run_blocking_reasons_report",
    "run_profile_comparison",
    "run_signal_calibration",
    "run_threshold_sweep_report",
    "write_profile_comparison",
]
