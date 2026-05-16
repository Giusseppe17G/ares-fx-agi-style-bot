"""Weighted strategy ensemble with regime-aware voting and promotion gating."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..contracts import MarketSnapshot, Regime, SignalAction, StrategySignal
from . import (
    strategy_breakout_compression,
    strategy_liquidity_sweep,
    strategy_mean_reversion,
    strategy_session_momentum,
    strategy_trend_pullback,
    strategy_volatility_expansion,
)
from .scoring_engine import (
    PromotionDecision,
    PromotionEvidence,
    clamp_score,
    detected_regime,
    evaluate_promotion_gate,
    none_signal,
)


STRATEGY_NAME = "strategy_ensemble"
STRATEGY_VERSION = "0.2.0"

StrategyEvaluator = Callable[[MarketSnapshot, Mapping[str, Any]], StrategySignal]


REGIME_WEIGHTS: Mapping[Regime, Mapping[str, float]] = {
    Regime.TREND_UP: {
        "trend_pullback": 1.40,
        "session_momentum": 1.15,
        "volatility_expansion": 1.05,
        "breakout_compression": 0.95,
        "liquidity_sweep": 0.80,
        "mean_reversion": 0.45,
    },
    Regime.TREND_DOWN: {
        "trend_pullback": 1.40,
        "session_momentum": 1.15,
        "volatility_expansion": 1.05,
        "breakout_compression": 0.95,
        "liquidity_sweep": 0.80,
        "mean_reversion": 0.45,
    },
    Regime.RANGE: {
        "mean_reversion": 1.35,
        "liquidity_sweep": 1.10,
        "breakout_compression": 0.75,
        "trend_pullback": 0.55,
        "session_momentum": 0.70,
        "volatility_expansion": 0.65,
    },
    Regime.HIGH_VOLATILITY: {
        "volatility_expansion": 1.25,
        "liquidity_sweep": 1.05,
        "session_momentum": 0.95,
        "trend_pullback": 0.80,
        "breakout_compression": 0.75,
        "mean_reversion": 0.40,
    },
    Regime.LOW_VOLATILITY: {
        "breakout_compression": 1.25,
        "mean_reversion": 1.10,
        "liquidity_sweep": 0.80,
        "trend_pullback": 0.65,
        "session_momentum": 0.65,
        "volatility_expansion": 0.50,
    },
    Regime.SPREAD_DANGER: {},
    Regime.LIQUIDITY_THIN: {},
}

DEFAULT_EVALUATORS: tuple[StrategyEvaluator, ...] = (
    strategy_trend_pullback.evaluate,
    strategy_mean_reversion.evaluate,
    strategy_breakout_compression.evaluate,
    strategy_liquidity_sweep.evaluate,
    strategy_session_momentum.evaluate,
    strategy_volatility_expansion.evaluate,
)


@dataclass(frozen=True)
class EnsembleConfig:
    """Configurable ensemble thresholds, intentionally conservative."""

    mode: str = "shadow"
    threshold: float = 64.0
    min_margin: float = 7.0
    consensus_bonus: float = 2.5


def evaluate(
    snapshot: MarketSnapshot,
    features: Mapping[str, Any],
    *,
    mode: str = "shadow",
    promotion_evidence: PromotionEvidence | Mapping[str, Any] | None = None,
    evaluators: Sequence[StrategyEvaluator] = DEFAULT_EVALUATORS,
    config: EnsembleConfig | None = None,
) -> StrategySignal:
    """Return the regime-weighted ensemble StrategySignal.

    In demo mode the Strategy Promotion Gate must pass before any directional
    candidate is emitted. Shadow mode remains available for audited forward
    collection and does not imply execution permission.
    """

    cfg = config or EnsembleConfig(mode=mode)
    promotion = evaluate_promotion_gate(promotion_evidence, requested_mode=cfg.mode)
    if cfg.mode.strip().lower() == "demo" and not promotion.approved:
        return none_signal(
            STRATEGY_NAME,
            "; ".join(promotion.reasons),
            metadata={"version": STRATEGY_VERSION, "promotion_gate": _decision_payload(promotion)},
        )

    regime = detected_regime(features)
    if regime in {Regime.SPREAD_DANGER, Regime.LIQUIDITY_THIN}:
        return none_signal(
            STRATEGY_NAME,
            f"regime blocks strategy: {regime.value}",
            metadata={"version": STRATEGY_VERSION, "regime": regime.value},
        )

    child_signals = [evaluator(snapshot, features) for evaluator in evaluators]
    weights = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS[Regime.RANGE])
    buy_score, buy_weight, buy_votes = _weighted_action(child_signals, weights, SignalAction.BUY)
    sell_score, sell_weight, sell_votes = _weighted_action(child_signals, weights, SignalAction.SELL)
    buy_score = _with_consensus_bonus(buy_score, buy_votes, cfg.consensus_bonus)
    sell_score = _with_consensus_bonus(sell_score, sell_votes, cfg.consensus_bonus)

    metadata = {
        "version": STRATEGY_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "mode": promotion.effective_mode,
        "regime": regime.value,
        "promotion_gate": _decision_payload(promotion),
        "child_signals": [_signal_payload(signal) for signal in child_signals],
        "weighted_scores": {
            "buy": buy_score,
            "sell": sell_score,
            "buy_weight": buy_weight,
            "sell_weight": sell_weight,
        },
    }
    if buy_score < cfg.threshold and sell_score < cfg.threshold:
        return none_signal(STRATEGY_NAME, "ensemble score below threshold", metadata={**metadata, "blocking_reasons": ("ensemble score below threshold",)})
    if abs(buy_score - sell_score) < cfg.min_margin:
        return none_signal(STRATEGY_NAME, "ensemble directional conflict", metadata={**metadata, "blocking_reasons": ("ensemble directional conflict",)})

    action = SignalAction.BUY if buy_score > sell_score else SignalAction.SELL
    score = buy_score if action == SignalAction.BUY else sell_score
    reasons = _ensemble_reasons(child_signals, action)
    component_scores = _merge_component_scores(child_signals, action)
    metadata["component_scores"] = component_scores
    metadata["setup_quality"] = _setup_quality(score)
    metadata["blocking_reasons"] = ()
    return StrategySignal(
        action=action,
        score=score,
        reasons=reasons,
        strategy_name=STRATEGY_NAME,
        metadata=metadata,
    )


def _weighted_action(
    signals: Sequence[StrategySignal],
    weights: Mapping[str, float],
    action: SignalAction,
) -> tuple[float, float, int]:
    weighted_total = 0.0
    total_weight = 0.0
    votes = 0
    for signal in signals:
        if signal.action != action:
            continue
        weight = weights.get(signal.strategy_name, 1.0)
        weighted_total += signal.score * weight
        total_weight += weight
        votes += 1
    if total_weight <= 0:
        return 0.0, 0.0, 0
    return clamp_score(weighted_total / total_weight), total_weight, votes


def _with_consensus_bonus(score: float, votes: int, bonus: float) -> float:
    if votes <= 1:
        return clamp_score(score)
    return clamp_score(score + (votes - 1) * bonus)


def _ensemble_reasons(signals: Sequence[StrategySignal], action: SignalAction) -> tuple[str, ...]:
    reasons: list[str] = []
    for signal in signals:
        if signal.action == action and signal.reasons:
            reasons.append(f"{signal.strategy_name}: {signal.reasons[0]}")
    return tuple(reasons) or ("ensemble direction selected",)


def _signal_payload(signal: StrategySignal) -> Mapping[str, Any]:
    return {
        "strategy_name": signal.strategy_name,
        "action": signal.action.value,
        "score": signal.score,
        "reasons": signal.reasons,
        "metadata": dict(signal.metadata),
    }


def _decision_payload(decision: PromotionDecision) -> Mapping[str, Any]:
    return {
        "requested_mode": decision.requested_mode,
        "approved": decision.approved,
        "effective_mode": decision.effective_mode,
        "reasons": decision.reasons,
        "checks": dict(decision.checks),
    }


def _merge_component_scores(signals: Sequence[StrategySignal], action: SignalAction) -> Mapping[str, float]:
    values: dict[str, list[float]] = {}
    for signal in signals:
        if signal.action != action:
            continue
        components = signal.metadata.get("component_scores", {})
        if not isinstance(components, Mapping):
            continue
        for key, value in components.items():
            values.setdefault(str(key), []).append(float(value))
    return {key: sum(items) / len(items) for key, items in values.items() if items}


def _setup_quality(score: float) -> str:
    return "A" if score >= 82 else "B" if score >= 70 else "C" if score >= 58 else "D"
