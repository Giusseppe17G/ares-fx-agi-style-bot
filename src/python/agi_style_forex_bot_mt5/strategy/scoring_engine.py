"""Deterministic scoring helpers for strategy modules.

The strategy layer only emits candidate intent. It does not size positions,
build execution requests or bypass risk/execution gates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

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


@dataclass(frozen=True)
class PromotionEvidence:
    """Evidence required by the Strategy Promotion Gate."""

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


@dataclass(frozen=True)
class PromotionDecision:
    """Result of checking whether a strategy can run in shadow or demo mode."""

    requested_mode: str
    approved: bool
    effective_mode: str
    reasons: tuple[str, ...]
    checks: Mapping[str, bool] = field(default_factory=dict)


def evaluate_promotion_gate(
    evidence: PromotionEvidence | Mapping[str, Any] | None,
    *,
    requested_mode: str = "shadow",
) -> PromotionDecision:
    """Apply the Strategy Promotion Gate from PROJECT_SPEC.md section 12.1.

    Shadow mode is allowed for audit collection. Demo mode is blocked unless all
    required evidence is present and passes.
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
    checks = {
        "sample_size": data.historical_trades >= 200 or bool(data.statistical_justification),
        "profit_factor": data.oos_profit_factor > 1.15,
        "expected_payoff": data.oos_expected_payoff > 0,
        "drawdown": (
            data.max_drawdown_limit_pct > 0
            and data.oos_max_drawdown_pct < data.max_drawdown_limit_pct
        ),
        "profit_concentration": data.max_profit_concentration_pct <= 50.0,
        "spread_slippage_sensitivity": data.spread_slippage_sensitivity_passed,
        "walk_forward": (not data.optimization_used) or data.walk_forward_passed,
        "shadow_forward": (
            data.shadow_audit_complete
            and data.shadow_signals > 0
            and data.shadow_days > 0
        ),
    }
    failed = tuple(name for name, passed in checks.items() if not passed)
    if failed:
        return PromotionDecision(
            requested_mode=requested_mode,
            approved=False,
            effective_mode="shadow",
            reasons=tuple(f"promotion gate failed: {name}" for name in failed),
            checks=checks,
        )
    return PromotionDecision(
        requested_mode=requested_mode,
        approved=True,
        effective_mode="demo",
        reasons=("strategy promotion gate passed for demo mode",),
        checks=checks,
    )


def _coerce_evidence(evidence: PromotionEvidence | Mapping[str, Any] | None) -> PromotionEvidence:
    if isinstance(evidence, PromotionEvidence):
        return evidence
    if not evidence:
        return PromotionEvidence()
    return PromotionEvidence(
        historical_trades=int(evidence.get("historical_trades", 0)),
        statistical_justification=str(evidence.get("statistical_justification", "")),
        oos_profit_factor=float(evidence.get("oos_profit_factor", 0.0)),
        oos_expected_payoff=float(evidence.get("oos_expected_payoff", 0.0)),
        oos_max_drawdown_pct=float(evidence.get("oos_max_drawdown_pct", 100.0)),
        max_drawdown_limit_pct=float(evidence.get("max_drawdown_limit_pct", 0.0)),
        max_profit_concentration_pct=float(evidence.get("max_profit_concentration_pct", 100.0)),
        spread_slippage_sensitivity_passed=bool(
            evidence.get("spread_slippage_sensitivity_passed", False)
        ),
        walk_forward_passed=bool(evidence.get("walk_forward_passed", False)),
        optimization_used=bool(evidence.get("optimization_used", False)),
        shadow_signals=int(evidence.get("shadow_signals", 0)),
        shadow_days=int(evidence.get("shadow_days", 0)),
        shadow_audit_complete=bool(evidence.get("shadow_audit_complete", False)),
    )
