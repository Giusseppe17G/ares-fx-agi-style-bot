"""Diagnostic strategy probing for live forward data."""

from __future__ import annotations

from typing import Any, Mapping

from agi_style_forex_bot_mt5.calibration import effective_profile_config
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.strategy import evaluate_ensemble
from agi_style_forex_bot_mt5.strategy.strategy_ensemble import EnsembleConfig


def probe_live_strategies(
    *,
    config: BotConfig,
    runtime_payloads: Mapping[str, Mapping[str, Any]],
    features_by_symbol: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run the strategy engine in diagnostic mode without opening trades."""

    effective = effective_profile_config(config.signal_profile, source="forward-signal-diagnose", profile_config=config.profile_config or None)
    profile = {**effective.thresholds, **effective.filters, "name": effective.profile_name, "profile_hash": effective.profile_hash}
    rows: list[dict[str, Any]] = []
    near_misses: list[dict[str, Any]] = []
    for symbol, features in features_by_symbol.items():
        snapshot = runtime_payloads[symbol]["snapshot"]
        signal = evaluate_ensemble(
            snapshot,
            features,
            mode="shadow",
            config=EnsembleConfig(mode="shadow", threshold=float(profile["ensemble_min_score"])),
        )
        metadata = dict(signal.metadata)
        component_scores = dict(metadata.get("component_scores") or {})
        passed_thresholds, threshold_failures = _threshold_result(metadata, profile, ensemble_score=signal.score)
        stable_passed, stable_reason = _stable_filter_result(
            profile,
            symbol=symbol,
            strategy_name=signal.strategy_name,
            session=str(features.get("session", "")),
            regime=str(features.get("regime", "")),
        )
        if not stable_passed:
            passed_thresholds = False
            threshold_failures = (*threshold_failures, stable_reason)
        blockers = tuple(dict.fromkeys((*_blocking_reasons(signal, metadata), *threshold_failures)))
        near_distance = _near_miss_distance(signal.score, float(profile["ensemble_min_score"]))
        near = signal.action.value == "NONE" and near_distance <= float(profile.get("near_miss_window", 8.0))
        row = {
            "symbol": symbol,
            "strategy_name": signal.strategy_name,
            "action": signal.action.value,
            "signal_score": signal.score,
            "setup_score": float(metadata.get("setup_quality_score", metadata.get("setup_score", signal.score if signal.action.value != "NONE" else 0.0)) or 0.0),
            "ensemble_score": signal.score,
            "component_scores": component_scores,
            "thresholds_used": effective.thresholds,
            "profile_hash": effective.profile_hash,
            "passed_thresholds": passed_thresholds,
            "threshold_failures": threshold_failures,
            "blocking_reasons": blockers,
            "child_signals": metadata.get("child_signals", ()),
            "near_miss": near,
            "near_miss_distance": near_distance,
            "session": features.get("session", ""),
            "regime": features.get("regime", ""),
            "execution_attempted": False,
        }
        rows.append(row)
        if near:
            near_misses.append(
                {
                    **row,
                    "suggested_research_adjustment": "Inspect threshold sensitivity in research only; do not change forward-shadow automatically.",
                }
            )
        for child in _child_rows(symbol, metadata, effective.thresholds, features):
            rows.append(child)
            if child.get("near_miss"):
                near_misses.append({**child, "suggested_research_adjustment": "Inspect child strategy near miss in research only."})
    return rows, near_misses


def _child_rows(symbol: str, metadata: Mapping[str, Any], thresholds: Mapping[str, Any], features: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in metadata.get("child_signals", ()) or ():
        payload = dict(child)
        child_metadata = dict(payload.get("metadata") or {})
        score = float(payload.get("score", 0.0) or 0.0)
        action = str(payload.get("action", "NONE"))
        failures = ("ENSEMBLE_SCORE_LOW",) if score < float(thresholds.get("ensemble_min_score", 0.0) or 0.0) else ()
        blockers = tuple(child_metadata.get("blocking_reasons") or payload.get("reasons") or failures or ("NO_SETUP_DETECTED",))
        near_distance = _near_miss_distance(score, float(thresholds.get("ensemble_min_score", 0.0) or 0.0))
        near = action == "NONE" and near_distance <= float(thresholds.get("near_miss_window", 8.0) or 8.0)
        rows.append(
            {
                "symbol": symbol,
                "strategy_name": payload.get("strategy_name", ""),
                "parent_strategy_name": "strategy_ensemble",
                "action": action,
                "signal_score": score,
                "setup_score": float(child_metadata.get("setup_quality_score", child_metadata.get("setup_score", score if action != "NONE" else 0.0)) or 0.0),
                "ensemble_score": score,
                "component_scores": dict(child_metadata.get("component_scores") or {}),
                "thresholds_used": dict(thresholds),
                "passed_thresholds": not failures,
                "threshold_failures": failures,
                "blocking_reasons": blockers,
                "child_signals": (),
                "near_miss": near,
                "near_miss_distance": near_distance,
                "session": features.get("session", ""),
                "regime": features.get("regime", ""),
                "execution_attempted": False,
            }
        )
    return rows


def _threshold_result(metadata: Mapping[str, Any], profile: Mapping[str, Any], *, ensemble_score: float) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    component_scores = dict(metadata.get("component_scores") or {})
    if float(ensemble_score or 0.0) < float(profile["ensemble_min_score"]):
        failures.append("ENSEMBLE_SCORE_LOW")
    setup_score = float(metadata.get("setup_quality_score", metadata.get("setup_score", 0.0)) or 0.0)
    if setup_score and setup_score < float(profile["min_setup_score"]):
        failures.append("SETUP_SCORE_LOW")
    if component_scores:
        if min(float(value) for value in component_scores.values()) < float(profile["min_component_score"]):
            failures.append("COMPONENT_SCORE_LOW")
        checks = {
            "cost_fit": "COST_BLOCK",
            "structure_fit": "STRUCTURE_BLOCK",
            "volatility_fit": "VOLATILITY_BLOCK",
            "session_fit": "SESSION_BLOCK",
        }
        for key, code in checks.items():
            if float(component_scores.get(key, 0.0) or 0.0) < float(profile.get(f"{key}_min", profile.get(key.replace("_fit", "_fit_min"), 0.0)) or 0.0):
                failures.append(code)
    return not failures, tuple(dict.fromkeys(failures))


def _stable_filter_result(profile: Mapping[str, Any], *, symbol: str, strategy_name: str, session: str, regime: str) -> tuple[bool, str]:
    if profile.get("name") != "BALANCED_STABLE" or not profile.get("apply_stability_filters"):
        return True, ""
    if symbol.upper() in set(profile.get("disabled_symbols", [])):
        return False, "STABLE_SYMBOL_DISABLED"
    if strategy_name.upper() in {str(item).upper() for item in profile.get("disabled_strategies", [])}:
        return False, "STABLE_STRATEGY_DISABLED"
    if session.upper() in set(profile.get("blocked_sessions", [])):
        return False, "STABLE_SESSION_BLOCK"
    if regime.upper() in set(profile.get("blocked_regimes", [])):
        return False, "STABLE_REGIME_BLOCK"
    return True, ""


def _blocking_reasons(signal: Any, metadata: Mapping[str, Any]) -> tuple[str, ...]:
    reasons = metadata.get("blocking_reasons") or signal.reasons or ()
    result: list[str] = []
    for reason in reasons:
        text = str(reason).upper()
        if "ENSEMBLE" in text and "SCORE" in text:
            result.append("ENSEMBLE_SCORE_LOW")
        elif "SESSION" in text:
            result.append("SESSION_BLOCK")
        elif "REGIME" in text:
            result.append("REGIME_MISMATCH")
        elif "SPREAD" in text or "COST" in text:
            result.append("SPREAD_BLOCK")
        elif "VOLATILITY" in text:
            result.append("VOLATILITY_BLOCK")
        elif "STRUCTURE" in text:
            result.append("STRUCTURE_BLOCK")
        elif text:
            result.append(text.replace(" ", "_"))
    return tuple(dict.fromkeys(result or ("NO_SETUP_DETECTED",)))


def _near_miss_distance(score: float, threshold: float) -> float:
    return max(0.0, float(threshold) - float(score or 0.0))
