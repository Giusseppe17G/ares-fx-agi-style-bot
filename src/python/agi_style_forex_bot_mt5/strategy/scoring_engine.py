"""Deterministic scoring helpers for strategy modules.

The strategy layer only emits candidate intent. It does not size positions,
build execution requests or bypass risk/execution gates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
import math
import numbers
from typing import Any

import numpy as np

from ..contracts import MarketSnapshot, Regime, SignalAction, StrategySignal


FeatureMap = Mapping[str, Any]


def clamp_score(value: float) -> float:
    """Clamp a score to the StrategySignal 0-100 contract."""

    return max(0.0, min(100.0, float(value)))


def feature_float(features: FeatureMap, key: str, default: float = 0.0) -> float:
    """Read a numeric feature, failing closed to a conservative default."""

    value = features.get(key, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def feature_bool(features: FeatureMap, key: str, default: bool = False) -> bool:
    """Read a boolean-like feature."""

    value = features.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def feature_text(features: FeatureMap, key: str, default: str = "") -> str:
    """Read a text feature as an uppercase normalized label."""

    value = features.get(key, default)
    return str(value).strip().upper()


def detected_regime(features: FeatureMap) -> Regime:
    """Resolve a regime label, defaulting to RANGE when unknown."""

    value = features.get("regime", Regime.RANGE)
    if isinstance(value, Regime):
        return value
    try:
        return Regime(str(value).strip().upper())
    except ValueError:
        return Regime.RANGE


def spread_is_unsafe(
    snapshot: MarketSnapshot,
    features: FeatureMap,
    default_max_spread_points: float = 25.0,
) -> bool:
    """Return True when strategy should fail closed on spread awareness."""

    max_spread = feature_float(features, "max_strategy_spread_points", default_max_spread_points)
    spread = feature_float(features, "spread_points", snapshot.spread_points)
    return spread < 0 or spread > max_spread


def score_conditions(
    *,
    base: float,
    conditions: Sequence[tuple[bool, float, str]],
) -> tuple[float, tuple[str, ...]]:
    """Score weighted conditions and return matched human-readable reasons."""

    score = base
    reasons: list[str] = []
    for passed, weight, reason in conditions:
        if passed:
            score += weight
            reasons.append(reason)
    return clamp_score(score), tuple(reasons)


def choose_direction(
    *,
    buy_score: float,
    sell_score: float,
    buy_reasons: Sequence[str],
    sell_reasons: Sequence[str],
    threshold: float,
    min_margin: float,
    strategy_name: str,
    metadata: Mapping[str, Any] | None = None,
) -> StrategySignal:
    """Choose BUY, SELL or NONE using a score threshold and conflict margin."""

    buy_score = clamp_score(buy_score)
    sell_score = clamp_score(sell_score)
    if buy_score < threshold and sell_score < threshold:
        return StrategySignal(
            action=SignalAction.NONE,
            score=0,
            reasons=("score below threshold",),
            strategy_name=strategy_name,
            metadata={**dict(metadata or {}), "blocking_reasons": ("score below threshold",), "required_data_missing": False},
        )
    if abs(buy_score - sell_score) < min_margin:
        return StrategySignal(
            action=SignalAction.NONE,
            score=0,
            reasons=("directional conflict",),
            strategy_name=strategy_name,
            metadata={**dict(metadata or {}), "blocking_reasons": ("directional conflict",), "required_data_missing": False},
        )
    if buy_score > sell_score:
        return StrategySignal(
            action=SignalAction.BUY,
            score=buy_score,
            reasons=tuple(buy_reasons),
            strategy_name=strategy_name,
            metadata={**dict(metadata or {}), "blocking_reasons": (), "required_data_missing": False},
        )
    return StrategySignal(
        action=SignalAction.SELL,
        score=sell_score,
        reasons=tuple(sell_reasons),
        strategy_name=strategy_name,
        metadata={**dict(metadata or {}), "blocking_reasons": (), "required_data_missing": False},
    )


def none_signal(strategy_name: str, reason: str, metadata: Mapping[str, Any] | None = None) -> StrategySignal:
    """Build a fail-closed NONE signal."""

    return StrategySignal(
        action=SignalAction.NONE,
        score=0,
        reasons=(reason,),
        strategy_name=strategy_name,
        metadata={**dict(metadata or {}), "blocking_reasons": (reason,), "required_data_missing": "missing" in reason.lower() or "insufficient" in reason.lower()},
    )


@dataclass(frozen=True)
class SetupScore:
    """Advanced setup quality score with component breakdown."""

    final_score: float
    component_scores: Mapping[str, float]
    reasons: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    suggested_strategy_name: str
    setup_quality: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_score": self.final_score,
            "component_scores": dict(self.component_scores),
            "reasons": self.reasons,
            "blocking_reasons": self.blocking_reasons,
            "suggested_strategy_name": self.suggested_strategy_name,
            "setup_quality": self.setup_quality,
        }


def score_setup_quality(
    *,
    strategy_name: str,
    features: FeatureMap,
    snapshot: MarketSnapshot | None = None,
    direction: str = "",
) -> SetupScore:
    """Score setup quality across regime, structure, momentum, costs and context."""

    regime = detected_regime(features)
    session = feature_text(features, "session", "")
    spread = feature_float(features, "spread_points", snapshot.spread_points if snapshot else 0.0)
    max_spread = feature_float(features, "max_strategy_spread_points", 25.0)
    component_scores = {
        "regime_fit": _regime_component(strategy_name, regime),
        "structure_fit": _structure_component(features, direction),
        "momentum_fit": _momentum_component(features, direction),
        "volatility_fit": _volatility_component(features),
        "cost_fit": clamp_score(100.0 - (spread / max(max_spread, 1.0) * 100.0)),
        "session_fit": 80.0 if session in {"LONDON", "NEW_YORK", "NY", "LONDON_NY_OVERLAP", "OVERLAP"} else 55.0 if session else 45.0,
        "liquidity_fit": _liquidity_component(features, direction),
        "risk_reward_fit": feature_float(features, "risk_reward_score", 70.0),
        "broker_fit": feature_float(features, "broker_readiness_score", 80.0),
        "portfolio_fit": feature_float(features, "portfolio_fit", 75.0),
    }
    final = clamp_score(sum(component_scores.values()) / len(component_scores))
    blocking: list[str] = []
    if component_scores["cost_fit"] < 30:
        blocking.append("cost fit below threshold")
    if component_scores["regime_fit"] < 35:
        blocking.append("regime fit below threshold")
    quality = "A" if final >= 82 else "B" if final >= 70 else "C" if final >= 58 else "D"
    reasons = tuple(f"{key}={round(value, 1)}" for key, value in component_scores.items() if value >= 70)
    return SetupScore(final, component_scores, reasons, tuple(blocking), strategy_name, quality)


def strategy_metadata(
    *,
    strategy_version: str,
    features: FeatureMap,
    snapshot: MarketSnapshot,
    strategy_name: str,
    direction: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    setup = score_setup_quality(strategy_name=strategy_name, features=features, snapshot=snapshot, direction=direction)
    return {
        "version": strategy_version,
        "strategy_version": strategy_version,
        "component_scores": setup.component_scores,
        "setup_quality_score": setup.final_score,
        "setup_quality": setup.setup_quality,
        "blocking_reasons": setup.blocking_reasons,
        "required_data_missing": False,
        "regime": feature_text(features, "regime", detected_regime(features).value),
        "session": feature_text(features, "session", ""),
        "spread_points": feature_float(features, "spread_points", snapshot.spread_points),
        **dict(extra or {}),
    }


def _regime_component(strategy_name: str, regime: Regime) -> float:
    preferred = {
        "trend_pullback": {Regime.TREND_UP, Regime.TREND_DOWN},
        "mean_reversion": {Regime.RANGE},
        "breakout_compression": {Regime.LOW_VOLATILITY, Regime.RANGE},
        "liquidity_sweep": {Regime.RANGE, Regime.HIGH_VOLATILITY},
        "session_momentum": {Regime.TREND_UP, Regime.TREND_DOWN},
        "volatility_expansion": {Regime.HIGH_VOLATILITY, Regime.TREND_UP, Regime.TREND_DOWN},
    }
    if regime in preferred.get(strategy_name, set()):
        return 90.0
    if regime in {Regime.SPREAD_DANGER, Regime.LIQUIDITY_THIN}:
        return 0.0
    return 55.0


def _structure_component(features: FeatureMap, direction: str) -> float:
    structure = feature_text(features, "trend_structure", "")
    bos = feature_text(features, "break_of_structure", "")
    direction = direction.upper()
    if direction == "BUY" and (structure == "UP" or bos == "BULLISH"):
        return 90.0
    if direction == "SELL" and (structure == "DOWN" or bos == "BEARISH"):
        return 90.0
    if not direction:
        return 65.0
    return 45.0


def _momentum_component(features: FeatureMap, direction: str) -> float:
    momentum = feature_float(features, "momentum_points", feature_float(features, "momentum", 0.0))
    if direction.upper() == "BUY" and momentum > 0:
        return 85.0
    if direction.upper() == "SELL" and momentum < 0:
        return 85.0
    if abs(momentum) < 1e-9:
        return 55.0
    return 40.0


def _volatility_component(features: FeatureMap) -> float:
    percentile = feature_float(features, "atr_percentile", 50.0)
    if 25 <= percentile <= 80:
        return 80.0
    if percentile > 90:
        return 45.0
    return 60.0


def _liquidity_component(features: FeatureMap, direction: str) -> float:
    if direction.upper() == "BUY" and (feature_bool(features, "reclaimed_low") or feature_bool(features, "swept_prev_low")):
        return 90.0
    if direction.upper() == "SELL" and (feature_bool(features, "reclaimed_high") or feature_bool(features, "swept_prev_high")):
        return 90.0
    return 60.0


# Strategy Promotion Gate thresholds (PROJECT_SPEC.md 12.1). Demo mode needs the
# 12.1 OOS criteria, the APPROVED_FOR_SHADOW_OBSERVATION minimums of
# docs/STRATEGY_PROMOTION_GATE.md, its Phase 8 forward-shadow evidence and the
# deflated statistics of docs/decisions/2026-10-22-deflated-promotion-gate.md.
# Where thresholds overlap every check runs, so the strictest one applies.
SHADOW_APPROVAL_CLASSIFICATION = "APPROVED_FOR_SHADOW_OBSERVATION"
SHADOW_APPROVAL_MIN_TRADES = 300
SHADOW_APPROVAL_MIN_PROFIT_FACTOR = 1.25
SHADOW_APPROVAL_MAX_DRAWDOWN_PCT = 12.0
FORWARD_SHADOW_MIN_DAYS = 14
FORWARD_SHADOW_MIN_TRADES = 200
FORWARD_SHADOW_MIN_PROFIT_FACTOR = 1.15
PSR_ZERO_MIN = 0.95
MIN_TRACK_RECORD_CONFIDENCE = 0.95
# PSR, MinTRL and the Newey-West t are asymptotic. Below this many observations
# a zero-edge sequence passes them more often than 5% (with positively
# autocorrelated returns and the pre-registered t >= 2.0 at 30-40 observations,
# for example); at 60 every simulated case stays at or below 5%. The floor holds
# in addition to n >= MinTRL. See the decision record for the simulation.
MIN_RETURN_OBSERVATIONS = 60
DEFLATED_SHARPE_MIN = 0.95
NEWEY_WEST_T_MIN = 3.0
NEWEY_WEST_T_MIN_SINGLE_PREREGISTERED = 2.0
PBO_MAX = 0.10

_TRUE_TEXT = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class PromotionEvidence:
    """Evidence required by the Strategy Promotion Gate.

    Every field defaults to a value that fails its check, so evidence that is
    not supplied keeps demo mode rejected. The fields after
    ``shadow_audit_complete`` were added by
    docs/decisions/2026-10-22-deflated-promotion-gate.md.
    """

    historical_trades: int = 0
    statistical_justification: str = ""
    oos_profit_factor: float = 0.0
    oos_expected_payoff: float = 0.0
    oos_max_drawdown_pct: float = 100.0
    max_drawdown_limit_pct: float = 0.0
    max_profit_concentration_pct: float = 100.0
    spread_slippage_sensitivity_passed: bool = False
    walk_forward_passed: bool = False
    optimization_used: bool = False
    shadow_signals: int = 0
    shadow_days: int = 0
    shadow_audit_complete: bool = False
    # (a) APPROVED_FOR_SHADOW_OBSERVATION minimums. historical_trades,
    # oos_profit_factor and oos_max_drawdown_pct above are checked again
    # against the stricter shadow-approval thresholds.
    shadow_approval_classification: str = ""
    oos_expectancy_r: float = 0.0
    # (b) Phase 8 forward-shadow evidence. shadow_days above is its duration;
    # forward_controls_passed attests the qualitative Phase 8 items (drawdown
    # controlled, no severe cost or performance drift, spread compatible,
    # storage stable, order_send never called).
    forward_paper_trades: int = 0
    forward_profit_factor: float = 0.0
    forward_expectancy_r: float = 0.0
    forward_controls_passed: bool = False
    # Deflated statistics: computed by the gate from a per-trade or per-day
    # return sequence, supplied by a caller that computed them with
    # research/edge_statistics.py, or both (the less favourable value wins).
    # A supplied return_sequence shorter than MIN_RETURN_OBSERVATIONS is
    # unusable, and the observations behind the statistics (the sequence length
    # or sharpe_observations, whichever is smaller) must reach both that floor
    # and MinTRL. trials counts every configuration tried, including the
    # selected one; trial_sharpes must likewise include the selected one.
    return_sequence: tuple[float, ...] = ()
    trials: int = 0
    trial_sharpes: tuple[float, ...] = ()
    single_preregistered_hypothesis: bool = False
    psr_zero: float | None = None
    min_track_record_length: float | None = None
    sharpe_observations: int = 0
    deflated_sharpe: float | None = None
    newey_west_t: float | None = None
    pbo: float | None = None


@dataclass(frozen=True)
class PromotionDecision:
    """Result of checking whether a strategy can run in shadow or demo mode."""

    requested_mode: str
    approved: bool
    effective_mode: str
    reasons: tuple[str, ...]
    checks: Mapping[str, bool] = field(default_factory=dict)
    statistics: Mapping[str, Any] = field(default_factory=dict)


def evaluate_promotion_gate(
    evidence: PromotionEvidence | Mapping[str, Any] | None,
    *,
    requested_mode: str = "shadow",
) -> PromotionDecision:
    """Apply the Strategy Promotion Gate from PROJECT_SPEC.md section 12.1.

    Shadow mode is allowed for audit collection. Demo mode is blocked unless all
    required evidence is present and passes: the 12.1 OOS criteria, the
    shadow-approval minimums, the Phase 8 forward-shadow evidence and the
    deflated statistics (at least MIN_RETURN_OBSERVATIONS observations, PSR,
    MinTRL, DSR given the trials tried, Newey-West t, PBO). Missing, malformed,
    non-finite or too-short evidence fails its check. An
    approval never sends anything: broker execution stays removed.
    """

    mode = requested_mode.strip().lower()
    if mode not in {"shadow", "demo"}:
        return PromotionDecision(
            requested_mode=requested_mode,
            approved=False,
            effective_mode="shadow",
            reasons=("unsupported strategy mode",),
            checks={"mode_supported": False},
        )
    if mode == "shadow":
        return PromotionDecision(
            requested_mode=requested_mode,
            approved=True,
            effective_mode="shadow",
            reasons=("shadow mode only; signals are for audit, not execution",),
            checks={"shadow_mode_allowed": True},
        )

    data = _coerce_evidence(evidence)
    historical_trades = _whole_number(data.historical_trades)
    justification = data.statistical_justification if isinstance(data.statistical_justification, str) else ""
    oos_profit_factor = _real(data.oos_profit_factor)
    oos_drawdown = _real(data.oos_max_drawdown_pct)
    drawdown_limit = _real(data.max_drawdown_limit_pct)
    shadow_days = _real(data.shadow_days)
    statistical_checks, statistics = _deflated_checks(data)
    checks = {
        # PROJECT_SPEC.md 12.1 OOS criteria, thresholds unchanged.
        "sample_size": _at_least(historical_trades, 200) or bool(justification),
        "profit_factor": _above(oos_profit_factor, 1.15),
        "expected_payoff": _above(_real(data.oos_expected_payoff), 0.0),
        "drawdown": _above(drawdown_limit, 0.0) and _below(oos_drawdown, drawdown_limit),
        "profit_concentration": _at_most(_real(data.max_profit_concentration_pct), 50.0),
        "spread_slippage_sensitivity": _flag(data.spread_slippage_sensitivity_passed),
        "walk_forward": _declared_false(data.optimization_used) or _flag(data.walk_forward_passed),
        "shadow_forward": (
            _flag(data.shadow_audit_complete)
            and _above(_whole_number(data.shadow_signals), 0)
            and _above(shadow_days, 0)
        ),
        # (a) APPROVED_FOR_SHADOW_OBSERVATION minimums.
        "shadow_approval_classification": _text(data.shadow_approval_classification) == SHADOW_APPROVAL_CLASSIFICATION,
        "shadow_approval_sample_size": (
            _at_least(historical_trades, SHADOW_APPROVAL_MIN_TRADES) or bool(justification.strip())
        ),
        "shadow_approval_profit_factor": _above(oos_profit_factor, SHADOW_APPROVAL_MIN_PROFIT_FACTOR),
        "shadow_approval_drawdown": (
            _at_least(oos_drawdown, 0.0) and _below(oos_drawdown, SHADOW_APPROVAL_MAX_DRAWDOWN_PCT)
        ),
        "shadow_approval_expectancy_r": _above(_real(data.oos_expectancy_r), 0.0),
        # (b) Phase 8 forward shadow: two weeks AND 200 paper trades.
        "forward_shadow_duration": _at_least(shadow_days, FORWARD_SHADOW_MIN_DAYS),
        "forward_shadow_trades": _at_least(_whole_number(data.forward_paper_trades), FORWARD_SHADOW_MIN_TRADES),
        "forward_profit_factor": _above(_real(data.forward_profit_factor), FORWARD_SHADOW_MIN_PROFIT_FACTOR),
        "forward_expectancy_r": _above(_real(data.forward_expectancy_r), 0.0),
        "forward_controls": _flag(data.forward_controls_passed),
        # Deflated statistics.
        **statistical_checks,
    }
    failed = tuple(name for name, passed in checks.items() if not passed)
    if failed:
        return PromotionDecision(
            requested_mode=requested_mode,
            approved=False,
            effective_mode="shadow",
            reasons=tuple(f"promotion gate failed: {name}" for name in failed),
            checks=checks,
            statistics=statistics,
        )
    return PromotionDecision(
        requested_mode=requested_mode,
        approved=True,
        effective_mode="demo",
        reasons=("strategy promotion gate passed for demo mode",),
        checks=checks,
        statistics=statistics,
    )


def _coerce_evidence(evidence: PromotionEvidence | Mapping[str, Any] | None) -> PromotionEvidence:
    """Map evidence onto PromotionEvidence; values are parsed fail-closed at check time."""

    if isinstance(evidence, PromotionEvidence):
        return evidence
    if not isinstance(evidence, Mapping) or not evidence:
        return PromotionEvidence()
    return PromotionEvidence(
        **{item.name: evidence[item.name] for item in fields(PromotionEvidence) if item.name in evidence}
    )


def _deflated_checks(data: PromotionEvidence) -> tuple[dict[str, bool], dict[str, Any]]:
    """Observation floor, PSR(0), MinTRL, DSR, Newey-West t and PBO checks plus their audit values."""

    # Imported here: the research package imports the backtester, which imports
    # this strategy package.
    from ..research import edge_statistics

    trials = _whole_number(data.trials)
    trials_declared = trials is not None and trials >= 1
    sequence, sequence_ok = _finite_series(data.return_sequence)
    # A supplied sequence below the floor is unusable evidence: it invalidates
    # the deflated block even when valid caller statistics are also given.
    sequence_long_enough = sequence.size == 0 or sequence.size >= MIN_RETURN_OBSERVATIONS
    trial_sharpes, trial_sharpes_ok = _finite_series(data.trial_sharpes)
    effective_trials = max(trials if trials_declared else 0, int(trial_sharpes.size))
    caller, caller_ok = _caller_statistics(data)

    computed: dict[str, Any] = {}
    computed_ok = True
    if sequence_ok and sequence.size:
        try:
            computed = _sequence_statistics(edge_statistics, sequence, trial_sharpes, effective_trials)
        except (ValueError, ZeroDivisionError, OverflowError):
            computed, computed_ok = {}, False
    caller_supplied = any(caller[name] is not None for name in ("psr_zero", "min_track_record_length", "deflated_sharpe", "newey_west_t"))
    valid = (
        sequence_ok
        and sequence_long_enough
        and trial_sharpes_ok
        and caller_ok
        and computed_ok
        and (bool(computed) or caller_supplied)
    )

    # The less favourable of the computed and the supplied value wins.
    psr_zero = _least_favourable(min, computed.get("psr_zero"), caller["psr_zero"])
    deflated = _least_favourable(min, computed.get("deflated_sharpe"), caller["deflated_sharpe"])
    newey_west = _least_favourable(min, computed.get("newey_west_t"), caller["newey_west_t"])
    min_trl = _least_favourable(max, computed.get("min_track_record_length"), caller["min_track_record_length"])
    observations = _least_favourable(min, computed.get("observations"), caller["observations"])
    single_preregistered = data.single_preregistered_hypothesis is True and effective_trials == 1
    t_threshold = NEWEY_WEST_T_MIN_SINGLE_PREREGISTERED if single_preregistered else NEWEY_WEST_T_MIN
    pbo = _real(data.pbo)

    checks = {
        "trials_declared": trials_declared,
        "deflated_inputs_valid": valid,
        "minimum_observations": valid and _at_least(observations, MIN_RETURN_OBSERVATIONS),
        "psr_zero": valid and _at_least(psr_zero, PSR_ZERO_MIN),
        "min_track_record_length": (
            valid
            and observations is not None
            and min_trl is not None
            and math.isfinite(min_trl)
            and observations >= min_trl
        ),
        "deflated_sharpe": valid and trials_declared and _at_least(deflated, DEFLATED_SHARPE_MIN),
        "newey_west_t": valid and _at_least(newey_west, t_threshold),
        "pbo": pbo is not None and 0.0 <= pbo <= PBO_MAX,
    }
    source = "+".join(name for name, present in (("return_sequence", bool(computed)), ("caller", caller_supplied)) if present)
    statistics = {
        "source": source or "none",
        "observations": observations,
        "observations_min": MIN_RETURN_OBSERVATIONS,
        "return_sequence_length": int(sequence.size),
        "sharpe": computed.get("sharpe"),
        "skew": computed.get("skew"),
        "kurtosis": computed.get("kurtosis"),
        "psr_zero": psr_zero,
        "psr_zero_min": PSR_ZERO_MIN,
        "min_track_record_length": min_trl,
        "min_track_record_confidence": MIN_TRACK_RECORD_CONFIDENCE,
        "deflated_sharpe": deflated,
        "deflated_sharpe_min": DEFLATED_SHARPE_MIN,
        "dsr_benchmark_sharpe": computed.get("dsr_benchmark_sharpe"),
        "dsr_benchmark_variance": computed.get("dsr_benchmark_variance"),
        "trials": effective_trials,
        "trial_sharpes_supplied": int(trial_sharpes.size),
        "single_preregistered_hypothesis": single_preregistered,
        "newey_west_t": newey_west,
        "newey_west_t_threshold": t_threshold,
        "pbo": pbo,
        "pbo_max": PBO_MAX,
    }
    return checks, {key: _json_number(value) for key, value in statistics.items()}


def _sequence_statistics(edge_statistics: Any, sequence: np.ndarray, trial_sharpes: np.ndarray, trials: int) -> dict[str, Any]:
    """Deflated statistics of one return sequence (raises ValueError when unusable)."""

    observations = int(sequence.size)
    sharpe = edge_statistics.sharpe_ratio(sequence)
    skew, kurtosis = edge_statistics.moments(sequence)
    result: dict[str, Any] = {
        "observations": observations,
        "sharpe": sharpe,
        "skew": skew,
        "kurtosis": kurtosis,
        "psr_zero": edge_statistics.probabilistic_sharpe_ratio(sharpe, 0.0, observations, skew, kurtosis),
        "min_track_record_length": edge_statistics.min_track_record_length(
            sharpe, 0.0, skew, kurtosis, MIN_TRACK_RECORD_CONFIDENCE
        ),
        "newey_west_t": edge_statistics.newey_west_t_stat(sequence),
    }
    if trials >= 1:
        # Under the null every trial has zero true Sharpe and its estimate has
        # variance 1/(n-1); the supplied trial Sharpes can only raise that.
        null_variance = 1.0 / (observations - 1)
        trial_variance = float(np.var(trial_sharpes, ddof=1)) if trial_sharpes.size > 1 else 0.0
        variance = max(null_variance, trial_variance)
        benchmark = edge_statistics.expected_max_sharpe(trials, variance)
        result["dsr_benchmark_variance"] = variance
        result["dsr_benchmark_sharpe"] = benchmark
        result["deflated_sharpe"] = edge_statistics.probabilistic_sharpe_ratio(
            sharpe, benchmark, observations, skew, kurtosis
        )
    return result


def _caller_statistics(data: PromotionEvidence) -> tuple[dict[str, Any], bool]:
    """Caller-computed statistics; anything supplied but malformed invalidates them all."""

    values: dict[str, Any] = {}
    valid = True
    for name, low, high in (
        ("psr_zero", 0.0, 1.0),
        ("deflated_sharpe", 0.0, 1.0),
        ("newey_west_t", -math.inf, math.inf),
        ("min_track_record_length", 0.0, math.inf),
    ):
        raw = getattr(data, name)
        number = None if raw is None else _real(raw)
        if raw is not None and (number is None or not low <= number <= high or (name == "newey_west_t" and not math.isfinite(number))):
            valid = False
            number = None
        if name == "min_track_record_length" and number is not None and number <= 0.0:
            valid = False
            number = None
        values[name] = number
    raw_observations = data.sharpe_observations
    observations = _whole_number(raw_observations)
    if raw_observations is None or observations == 0:
        values["observations"] = None
    elif observations is None or observations < 0:
        valid = False
        values["observations"] = None
    else:
        values["observations"] = observations
    return values, valid


def _finite_series(value: Any) -> tuple[np.ndarray, bool]:
    """A one-dimensional finite float array; strings, mappings and scalars are invalid."""

    empty = np.empty(0, dtype=float)
    if value is None:
        return empty, True
    if isinstance(value, (str, bytes, Mapping)):
        return empty, False
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return empty, False
    if array.ndim != 1 or not np.isfinite(array).all():
        return empty, False
    return array, True


def _least_favourable(pick: Any, *values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return pick(present) if present else None


def _json_number(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def _real(value: Any) -> float | None:
    """A real number (infinity allowed); None for NaN, booleans and non-numbers."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, numbers.Real):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return None if math.isnan(number) else number


def _whole_number(value: Any) -> int | None:
    number = _real(value)
    if number is None or not math.isfinite(number) or not number.is_integer():
        return None
    return int(number)


def _flag(value: Any) -> bool:
    """True only for an explicit pass: True, 1 or a true-like text."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_TEXT
    if isinstance(value, numbers.Integral):
        return int(value) == 1
    if getattr(getattr(value, "dtype", None), "kind", "") == "b":
        return bool(value)
    return False


def _declared_false(value: Any) -> bool:
    """True only for an explicit boolean False; anything else counts as set."""

    if isinstance(value, bool):
        return value is False
    if getattr(getattr(value, "dtype", None), "kind", "") == "b":
        return not bool(value)
    return False


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _above(value: float | None, threshold: float) -> bool:
    return value is not None and value > threshold


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _below(value: float | None, threshold: float | None) -> bool:
    return value is not None and threshold is not None and value < threshold


def _at_most(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold
