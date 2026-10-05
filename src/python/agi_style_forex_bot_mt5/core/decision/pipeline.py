"""Compose the existing decision modules without inventing portfolio state.

The caller owns market/account acquisition, persisted daily references, feature
causality, the model artifact, and audit storage. This module owns ordering and
fail-closed propagation. Acceptance permits further *paper* evaluation only; it
does not authorize an execution request or replace durable decision auditing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Any, Callable, Mapping, Sequence

from ...config import BotConfig
from ...calibration.decision_policy import evaluate_profile_thresholds, evaluate_stability_filters, resolve_signal_profile
from ...contracts import AccountState, MarketSnapshot, RiskDecision, SignalAction, StrategySignal, TradeSignal
from ...data.strategy_features import _bar_duration
from ...risk import RiskRuntimeState
from ...risk.position_sizer import normalize_lot_down
from ...strategy import EnsembleConfig
from ..clock import Clock
from ..safety import SafetyEnvelope


STAGES = (
    "inputs", "strategy", "profile_thresholds", "stable_filters", "signal_construction", "signal_audit", "risk_engine",
    "ml_filter", "signal_ranker", "portfolio_guard", "dynamic_risk",
    "paper_limits", "risk_adjustment",
)


@dataclass(frozen=True)
class DecisionContext:
    """Explicit state at the decision cutoff; no implicit empty/safe book.

    ``features_available_at_utc`` is the latest availability time of *all* data
    used to build the features. ``state_available_at_utc`` identifies the
    account/portfolio observation. A model in use needs its actual artifact
    availability timestamp; historical replay must not use today's model.
    ``open_trades`` describes the portfolio being ranked. ``risk_state`` must
    contain every position/pending order whose risk the account bears.
    """

    decision_id: str
    config: BotConfig
    snapshot: MarketSnapshot
    features: Mapping[str, Any]
    features_available_at_utc: datetime
    state_available_at_utc: datetime
    account: AccountState
    risk_state: RiskRuntimeState
    open_trades: Sequence[Mapping[str, Any]]
    broker_symbol: str
    broker_readiness_score: float
    correlation: float | None
    shadow_paused: bool
    consecutive_losses: int
    allow_disabled_ml: bool
    ml_model_available_at_utc: datetime | None


@dataclass(frozen=True)
class StageTrace:
    stage_id: str
    status: str
    reason: str
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class PipelineDecision:
    decision_id: str
    timestamp_utc: datetime | None
    accepted: bool
    reject_code: str
    reject_reason: str
    strategy_signal: StrategySignal | None
    trade_signal: TradeSignal | None
    risk_decision: RiskDecision | None
    trace: tuple[StageTrace, ...]

    def to_dict(self) -> dict[str, Any]:
        # Do not serialize account IDs, broker servers or exception strings.
        return SafetyEnvelope().seal({
            "decision_id": self.decision_id,
            "timestamp_utc": self.timestamp_utc.isoformat() if self.timestamp_utc else None,
            "accepted": self.accepted,
            "reject_code": self.reject_code,
            "reject_reason": self.reject_reason,
            "strategy_signal": _jsonable(asdict(self.strategy_signal)) if self.strategy_signal else None,
            "trade_signal": _jsonable(asdict(self.trade_signal)) if self.trade_signal else None,
            "risk_decision": _jsonable(asdict(self.risk_decision)) if self.risk_decision else None,
            "trace": [stage.to_dict() for stage in self.trace],
            "scope": "PAPER_DECISION_ONLY",
            "execution_authorized": False,
            "decision_audit_required": True,
        }, full=True)


class SharedDecisionPipeline:
    """Delegate to existing modules, stopping at the first unverified stage.

    All dependencies are explicit. ``strategy_evaluator`` has evaluate_ensemble's
    signature. ``signal_builder(context, strategy)`` adapts the existing SL/TP
    construction and must return TradeSignal. ``persist_signal(signal, context)``
    must durably store the signal and return the literal bool True. Paper limits
    delegate via ``paper_limit_evaluator(context, now_utc)``. Caller callbacks
    must not execute orders; this API never supplies execution dependencies.
    """

    def __init__(
        self, *, clock: Clock, strategy_evaluator: Callable[..., StrategySignal],
        signal_builder: Callable[[DecisionContext, StrategySignal], TradeSignal],
        risk_engine: Any, ml_filter: Any, signal_ranker: Any,
        portfolio_guard: Any, dynamic_risk_allocator: Any,
        persist_signal: Callable[[TradeSignal, DecisionContext], bool],
        paper_limit_evaluator: Callable[[DecisionContext, datetime], Mapping[str, Any]],
    ) -> None:
        self.clock = clock
        self.strategy_evaluator = strategy_evaluator
        self.signal_builder = signal_builder
        self.risk_engine = risk_engine
        self.ml_filter = ml_filter
        self.signal_ranker = signal_ranker
        self.portfolio_guard = portfolio_guard
        self.dynamic_risk_allocator = dynamic_risk_allocator
        self.persist_signal = persist_signal
        self.paper_limit_evaluator = paper_limit_evaluator

    def evaluate(self, context: DecisionContext) -> PipelineDecision:
        now: datetime | None = None
        trace: list[StageTrace] = []
        strategy: StrategySignal | None = None
        signal: TradeSignal | None = None
        risk: RiskDecision | None = None
        stage = "inputs"

        def passed(payload: Mapping[str, Any], reason: str = "") -> None:
            trace.append(StageTrace(stage, "passed", reason, _jsonable(payload)))

        def finish(code: str = "", reason: str = "", *, error: bool = False,
                   payload: Mapping[str, Any] | None = None) -> PipelineDecision:
            final_risk = risk
            if code:
                trace.append(StageTrace(stage, "error" if error else "rejected", reason, _jsonable(payload or {})))
                for pending in STAGES[STAGES.index(stage) + 1:]:
                    trace.append(StageTrace(pending, "skipped", f"blocked_by:{stage}:{code}", {}))
                if risk is not None:
                    final_risk = replace(risk, accepted=False, approved_lot=0.0,
                                         risk_amount_account_currency=0.0,
                                         reject_code=code, reject_reason=reason)
            return PipelineDecision(context.decision_id, now, not bool(code), code,
                                    reason, strategy, signal, final_risk, tuple(trace))

        try:
            now = _aware(self.clock.now_utc())
            self._validate_context(context, now)
            profile = resolve_signal_profile(context.config)
            passed({"features_available_at_utc": context.features_available_at_utc.isoformat(),
                    "state_available_at_utc": context.state_available_at_utc.isoformat()})

            stage = "strategy"
            strategy = self.strategy_evaluator(context.snapshot, context.features, mode="shadow",
                                               config=EnsembleConfig(mode="shadow", threshold=float(profile["ensemble_min_score"])))
            if not isinstance(strategy, StrategySignal):
                return finish("STRATEGY_OUTPUT_INVALID", "strategy did not return StrategySignal")
            if strategy.action == SignalAction.NONE:
                return finish("NO_SIGNAL", "; ".join(strategy.reasons) or "strategy returned NONE",
                              payload=asdict(strategy))
            if strategy.action not in (SignalAction.BUY, SignalAction.SELL):
                return finish("STRATEGY_OUTPUT_INVALID", "unsupported strategy action")
            passed(asdict(strategy))

            stage = "profile_thresholds"
            profile_ok, failures = evaluate_profile_thresholds(strategy.metadata, profile, ensemble_score=strategy.score)
            profile_payload = {"profile_hash": profile["profile_hash"], "profile": profile["name"], "failures": failures}
            if not profile_ok:
                return finish("PROFILE_THRESHOLD_BLOCK", "; ".join(failures), payload=profile_payload)
            passed(profile_payload)

            stage = "stable_filters"
            stable_ok, stable_reason = evaluate_stability_filters(
                profile, symbol=context.snapshot.symbol, strategy_name=strategy.strategy_name,
                session=str(context.features["session"]), regime=str(context.features["regime"]),
            )
            if not stable_ok:
                return finish(stable_reason, "stability policy rejected the candidate")
            passed({"applied": bool(profile.get("apply_stability_filters")), "profile_hash": profile["profile_hash"]})

            stage = "signal_construction"
            signal = self.signal_builder(context, strategy)
            if not isinstance(signal, TradeSignal):
                return finish("SIGNAL_OUTPUT_INVALID", "signal builder did not return TradeSignal")
            # Caller-provided stable identity avoids wall-clock/UUID replay drift.
            signal = replace(signal, signal_id=context.decision_id)
            if signal.direction.value != strategy.action.value:
                return finish("SIGNAL_DIRECTION_MISMATCH", "signal and strategy direction disagree")
            _aware(signal.created_at_utc)
            if not all(_finite(value) for value in (signal.sl_price, signal.tp_price, signal.confidence)):
                return finish("SIGNAL_OUTPUT_INVALID", "signal contains non-finite prices or confidence")
            signal.validate_against_snapshot(context.snapshot)
            passed(asdict(signal))

            stage = "signal_audit"
            if self.persist_signal(signal, context) is not True:
                return finish("SIGNAL_AUDIT_FAILED", "signal was not durably persisted or enqueued")
            passed({"audit_confirmed": True})

            stage = "risk_engine"
            state = replace(context.risk_state, now_utc=now, audit_confirmed=True,
                            consecutive_losses=context.consecutive_losses)
            risk = self.risk_engine.evaluate(signal=signal, snapshot=context.snapshot,
                                             account=context.account, state=state)
            if not isinstance(risk, RiskDecision):
                risk = None
                return finish("RISK_OUTPUT_INVALID", "risk engine did not return RiskDecision")
            if risk.accepted is not True:
                return finish(risk.reject_code, risk.reject_reason, payload=asdict(risk))
            if risk.signal_id != signal.signal_id or not all(_finite(v) and v > 0 for v in
                    (risk.approved_lot, risk.risk_amount_account_currency, risk.open_risk_pct_after_trade)):
                return finish("RISK_OUTPUT_INVALID", "accepted risk decision is inconsistent")
            passed(asdict(risk))

            stage = "ml_filter"
            if context.ml_model_available_at_utc is not None and _aware(context.ml_model_available_at_utc) > now:
                return finish("ML_MODEL_FROM_FUTURE", "model was not available at decision time")
            bundle = getattr(self.ml_filter, "bundle", None)
            if isinstance(bundle, Mapping) and bundle.get("metadata", {}).get("approved_for_shadow_filtering") and context.ml_model_available_at_utc is None:
                return finish("ML_PROVENANCE_MISSING", "model availability timestamp is required")
            ml = self.ml_filter.approve_or_reject(signal, {**context.features, "score": strategy.score})
            ml_payload = ml.to_dict()
            if ml.ml_status == "ML_DISABLED":
                if not context.allow_disabled_ml:
                    return finish("ML_DISABLED_NOT_ALLOWED", "no approved ML artifact for this policy", payload=ml_payload)
                passed(ml_payload, "ML disabled by explicit paper policy")
            elif ml.ml_status != "ML_APPROVED":
                return finish(ml.ml_status if ml.ml_status in {"ML_REJECTED", "ML_ERROR"} else "ML_OUTPUT_INVALID",
                              "ML did not approve the signal", payload={"ml_status": ml.ml_status})
            elif context.ml_model_available_at_utc is None:
                return finish("ML_PROVENANCE_MISSING", "model availability timestamp is required")
            elif _aware(context.ml_model_available_at_utc) > now:
                return finish("ML_MODEL_FROM_FUTURE", "model was not available at decision time")
            elif not _finite(ml.probability_of_success) or not 0 <= ml.probability_of_success <= 1:
                return finish("ML_OUTPUT_INVALID", "ML probability is invalid")
            else:
                passed(ml_payload)

            stage = "signal_ranker"
            risk_pct = risk.risk_amount_account_currency / context.account.equity * 100.0
            candidate = {
                "symbol": signal.symbol, "broker_symbol": context.broker_symbol,
                "direction": signal.direction.value, "risk_pct": risk_pct,
                "strategy_name": strategy.strategy_name, "regime": str(context.features["regime"]),
                "session": str(context.features["session"]), "strategy_score": strategy.score,
                "ml_probability": ml.probability_of_success,
                "spread_percentile": context.features["spread_percentile"],
                "broker_readiness_score": context.broker_readiness_score,
                "correlation": context.correlation,
                "research_candidate_status": str(strategy.metadata.get("candidate_status", "")),
            }
            ranked_rows = self.signal_ranker.rank([candidate], top_n=1)
            if len(ranked_rows) != 1:
                return finish("RANKING_OUTPUT_INVALID", "one candidate must produce one ranking")
            ranked = ranked_rows[0]
            if ranked.get("ranking_decision") != "ACCEPT_TOP_N":
                return finish(str(ranked.get("ranking_decision") or "RANKING_OUTPUT_INVALID"),
                              "candidate not accepted by ranker", payload=ranked)
            passed(ranked)

            stage = "portfolio_guard"
            portfolio = self.portfolio_guard.evaluate(
                candidate=ranked, open_trades=context.open_trades, correlation=context.correlation,
                shadow_paused=context.shadow_paused, daily_drawdown_pct=abs(risk.daily_drawdown_pct),
                consecutive_losses=context.consecutive_losses,
            )
            if portfolio.accepted is not True:
                return finish(portfolio.reject_code, portfolio.reject_reason, payload=portfolio.to_dict())
            passed(portfolio.to_dict())

            stage = "dynamic_risk"
            dynamic = self.dynamic_risk_allocator.allocate({
                **portfolio.checks, "drawdown_pct": abs(risk.daily_drawdown_pct),
                "consecutive_losses": context.consecutive_losses,
                "spread_ratio": context.snapshot.spread_points / context.config.max_spread_points_default,
                "broker_readiness_score": context.broker_readiness_score,
                "ml_probability": ml.probability_of_success, "correlation": context.correlation,
                "symbol_watchlist": candidate["research_candidate_status"].upper() == "WATCHLIST",
            })
            if not _finite(dynamic.risk_multiplier) or not 0 < dynamic.risk_multiplier <= 1:
                return finish("DYNAMIC_RISK_ZERO" if dynamic.risk_multiplier == 0 else "DYNAMIC_RISK_INVALID",
                              "dynamic risk must be positive and may not increase risk", payload=dynamic.to_dict())
            passed(dynamic.to_dict())

            stage = "paper_limits"
            paper = dict(self.paper_limit_evaluator(context, now))
            SafetyEnvelope.from_mapping(paper).require_paper_only(context="paper limits")
            if paper.get("can_open_new_paper_trade") is not True or paper.get("blocking_reason"):
                return finish(str(paper.get("blocking_reason") or "PAPER_LIMITS_UNVERIFIED"),
                              "paper limits did not approve the candidate", payload=paper)
            passed(paper)

            stage = "risk_adjustment"
            multiplier = dynamic.risk_multiplier * context.config.paper_risk_multiplier
            lot = normalize_lot_down(risk.approved_lot * multiplier, context.snapshot)
            if lot <= 0:
                return finish("INVALID_LOT", "reduced risk cannot fit the broker minimum lot")
            applied_multiplier = lot / risk.approved_lot
            existing_risk_pct = risk.open_risk_pct_after_trade - risk_pct
            if existing_risk_pct < -1e-8:
                return finish("RISK_OUTPUT_INVALID", "aggregate risk is smaller than candidate risk")
            checks = {**dict(risk.checks), "portfolio_decision": portfolio.to_dict(),
                      "dynamic_risk": dynamic.to_dict(), "paper_limits": paper,
                      "effective_risk_pct": risk_pct * applied_multiplier,
                      "paper_risk_multiplier": context.config.paper_risk_multiplier}
            risk = replace(risk, approved_lot=lot,
                           risk_amount_account_currency=risk.risk_amount_account_currency * applied_multiplier,
                           open_risk_pct_after_trade=max(0.0, existing_risk_pct) + risk_pct * applied_multiplier,
                           checks=checks)
            passed(asdict(risk))
            return finish()
        except InputRejected as exc:
            return finish(exc.code, exc.reason)
        except Exception as exc:
            # Exception messages may contain credentials or broker/account IDs.
            return finish("DECISION_STAGE_ERROR", f"{stage} raised {type(exc).__name__}", error=True)

    def _validate_context(self, ctx: DecisionContext, now: datetime) -> None:
        if not _finite(ctx.config.paper_risk_multiplier) or not 0 < ctx.config.paper_risk_multiplier <= 1:
            raise InputRejected("PAPER_RISK_INVALID", "paper multiplier must be in (0, 1]")
        try:
            ctx.config.validate_safety()
        except (TypeError, ValueError) as exc:
            raise InputRejected("CONFIG_INVALID", "configuration violates the mandatory safety limits") from exc
        SafetyEnvelope.from_config(ctx.config).require_paper_only(context="shared decision")
        if getattr(self.risk_engine, "config", None) != ctx.config:
            raise InputRejected("CONFIG_MISMATCH", "risk engine and decision config differ")
        for key, ceiling in (("max_open_trades", 10), ("max_open_risk_pct", 5.0),
                ("max_risk_per_trade_pct", 0.5), ("max_daily_drawdown_pct", 3.0),
                ("max_floating_drawdown_pct", 5.0), ("max_market_snapshot_age_seconds", 5),
                ("max_signal_age_seconds", 30)):
            value = getattr(ctx.config, key)
            if not _finite(value) or not 0 < value <= ceiling:
                raise InputRejected("CONFIG_INVALID", f"{key} must be positive, finite and within project limits")
        if not ctx.decision_id or not ctx.broker_symbol:
            raise InputRejected("DECISION_CONTEXT_MISSING", "decision identity and broker symbol are required")
        for label, value in (("features", ctx.features_available_at_utc), ("state", ctx.state_available_at_utc)):
            instant = _aware(value)
            if instant > now:
                raise InputRejected("FUTURE_DATA", f"{label} was unavailable at decision time")
        state_age = (now - _aware(ctx.state_available_at_utc)).total_seconds()
        if state_age > ctx.config.max_market_snapshot_age_seconds:
            raise InputRejected("STALE_STATE", "account/portfolio state is stale")
        _aware(ctx.snapshot.timestamp_utc)
        ctx.snapshot.validate()
        age = (now - _aware(ctx.snapshot.timestamp_utc)).total_seconds()
        if not 0 <= age <= ctx.config.max_market_snapshot_age_seconds:
            raise InputRejected("MARKET_DATA_INVALID", "snapshot is stale or from the future")
        if not all(_finite(getattr(ctx.snapshot, key)) for key in (
                "bid", "ask", "spread_points", "digits", "point", "tick_value", "tick_size",
                "volume_min", "volume_max", "volume_step", "stops_level_points", "freeze_level_points")):
            raise InputRejected("MARKET_DATA_INVALID", "snapshot values must be finite")
        if not isinstance(ctx.features, Mapping) or not ctx.features or not all(ctx.features.get(k) for k in ("session", "regime")):
            raise InputRejected("FEATURE_CONTEXT_MISSING", "features, session and regime are required")
        try:
            duration = _bar_duration(ctx.snapshot.timeframe)
        except ValueError as exc:
            raise InputRejected("FEATURE_TIMEFRAME_INVALID", "feature timeframe has no known bar duration") from exc
        available = _aware(ctx.features_available_at_utc)
        feature_age = (now - available).total_seconds()
        if feature_age > duration.total_seconds() + ctx.config.max_market_snapshot_age_seconds:
            raise InputRejected("STALE_FEATURES", "latest closed-bar features are older than one bar plus snapshot tolerance")
        if "available_at_utc" in ctx.features and _evidence_timestamp(ctx.features["available_at_utc"]) != available:
            raise InputRejected("FEATURE_TEMPORAL_MISMATCH", "feature metadata and context availability disagree")
        if "source_bar_timestamp_utc" in ctx.features:
            source = _evidence_timestamp(ctx.features["source_bar_timestamp_utc"])
            if source + duration != available:
                raise InputRejected("FEATURE_TEMPORAL_MISMATCH", "feature source bar does not close at declared availability")
        if not all(_finite(v) and v > 0 for v in (ctx.account.balance, ctx.account.equity,
                ctx.risk_state.daily_equity_reference, ctx.risk_state.floating_drawdown_reference)):
            raise InputRejected("RISK_REFERENCE_MISSING", "account equity and both drawdown references must be finite and positive")
        if ctx.open_trades is None or ctx.risk_state.open_positions is None:
            raise InputRejected("POSITION_STATE_MISSING", "both portfolio and risk positions must be supplied")
        for position in ctx.risk_state.open_positions:
            if not all(_finite(getattr(position, key)) and getattr(position, key) > 0 for key in
                       ("volume", "entry_price", "sl_price", "tp_price")):
                raise InputRejected("POSITION_STATE_INVALID", "risk positions need finite volume and protective prices")
        for trade in ctx.open_trades:
            if not all(trade.get(key) for key in ("symbol", "direction", "strategy_name", "regime")) or not _finite(trade.get("risk_pct")) or trade["risk_pct"] < 0:
                raise InputRejected("POSITION_STATE_INVALID", "open trades must carry complete exposure context")
        if not isinstance(ctx.shadow_paused, bool) or not isinstance(ctx.allow_disabled_ml, bool):
            raise InputRejected("POLICY_STATE_INVALID", "pause and ML policy must be explicit booleans")
        if ctx.allow_disabled_ml != ctx.config.paper_allow_disabled_ml:
            raise InputRejected("CONFIG_MISMATCH", "ML disabled policy differs from the persisted config")
        if not isinstance(ctx.consecutive_losses, int) or ctx.consecutive_losses < 0:
            raise InputRejected("POLICY_STATE_INVALID", "consecutive loss count is invalid")
        if not _finite(ctx.broker_readiness_score) or not 0 < ctx.broker_readiness_score <= 100:
            raise InputRejected("BROKER_QUALITY_UNVERIFIED", "broker readiness score is required")
        if not _finite(ctx.features.get("spread_percentile")) or not 0 <= ctx.features["spread_percentile"] <= 100:
            raise InputRejected("SPREAD_PERCENTILE_UNVERIFIED", "observed spread percentile is required")
        if ctx.correlation is None and ctx.open_trades:
            raise InputRejected("CORRELATION_UNVERIFIED", "correlation is required for an exposed portfolio")
        if ctx.correlation is not None and (not _finite(ctx.correlation) or not -1 <= ctx.correlation <= 1):
            raise InputRejected("CORRELATION_UNVERIFIED", "correlation must be finite within [-1, 1]")
        if not _finite(ctx.config.max_spread_points_default) or ctx.config.max_spread_points_default <= 0:
            raise InputRejected("HIGH_SPREAD", "spread limit is invalid")


class InputRejected(ValueError):
    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InputRejected("TIMESTAMP_INVALID", "decision inputs require timezone-aware timestamps")
    return value.astimezone(timezone.utc)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _evidence_timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InputRejected("TIMESTAMP_INVALID", "feature metadata timestamp is invalid") from exc
    return _aware(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return type(value).__name__
