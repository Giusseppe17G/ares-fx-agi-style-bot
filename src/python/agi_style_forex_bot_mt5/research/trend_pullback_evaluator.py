"""Direct single-strategy, fixed-lot candidate research; no execution pipeline."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import math
from typing import Any

import pandas as pd

from ..backtesting.backtester import Backtester, BacktestOutcome, BacktestSettings, CostModel, ENGINE_VERSION, TradeCandidate
from ..contracts import Direction, MarketSnapshot, SignalAction
from ..core.decision.signal_builder import build_signal_prices
from ..core.instruments import InstrumentSpec
from ..data.strategy_features import prepare_strategy_features, strategy_features_at
from ..strategy.strategy_trend_pullback import STRATEGY_NAME, STRATEGY_VERSION, TrendPullbackResearchParams, evaluate
from .experiment_plan import (BAR_DURATION, EVALUATOR_VERSION, ExperimentPlan, ResearchManagement,
                              _binding, _digest, _number, _utc, _validate_instrument_cost,
                              normalize_research_bars)


@dataclass(frozen=True)
class CandidateGeneration:
    candidates: tuple[TradeCandidate, ...]
    decisions: tuple[dict[str, Any], ...]


def _snapshot(row: pd.Series, symbol: str, instrument: InstrumentSpec) -> MarketSnapshot:
    spread = float(row["spread_points"])
    half_spread = spread * instrument.point / 2
    return MarketSnapshot(
        symbol=symbol, timeframe="M5", timestamp_utc=(row["timestamp_utc"]+BAR_DURATION).to_pydatetime(),
        bid=float(row["close"])-half_spread, ask=float(row["close"])+half_spread,
        spread_points=spread, digits=instrument.digits, point=instrument.point,
        tick_size=instrument.tick_size, tick_value=instrument.tick_value,
        volume_min=instrument.min_volume, volume_max=instrument.max_volume, volume_step=instrument.volume_step,
        stops_level_points=instrument.stops_level_points, freeze_level_points=instrument.freeze_level_points,
    )


def generate_trend_pullback_candidates(candles: pd.DataFrame, *, symbol: str,
                                     params: TrendPullbackResearchParams, instrument: InstrumentSpec,
                                     cost_model: CostModel, management: ResearchManagement, lot: float,
                                     window_start: str | pd.Timestamp, window_end: str | pd.Timestamp,
                                     identity_prefix: str = "research") -> CandidateGeneration:
    """Audit all source bars in the window; exclude boundaries BEFORE outcomes.

    Future timestamps determine horizon availability. Their OHLC values never
    enter a decision. At most 250 preceding bars initialize this split's state.
    There is no ensemble consensus, profile promotion or portfolio simulation.
    """
    if not isinstance(params, TrendPullbackResearchParams) or not isinstance(management, ResearchManagement):
        raise ValueError("typed strategy parameters and management are required")
    _number(lot, "lot", positive=True)
    _validate_instrument_cost(instrument, cost_model, lot)
    if instrument.symbol != symbol or instrument.canonical_symbol != symbol:
        raise ValueError("instrument symbol mismatch")
    start, end = _utc(window_start), _utc(window_end)
    if start >= end:
        raise ValueError("window must be a positive interval")
    bars = normalize_research_bars(candles, symbol=symbol)
    # A bar straddling the boundary cannot initialize a state available at start.
    history = bars.loc[bars["timestamp_utc"] + BAR_DURATION <= start].tail(250)
    active = bars.loc[(bars["timestamp_utc"] >= start) & (bars["timestamp_utc"] < end)]
    if active.empty:
        return CandidateGeneration((), ())
    scoped = pd.concat([history, active], ignore_index=True)
    enriched = prepare_strategy_features(scoped, point=instrument.point, max_spread_points=cost_model.max_spread_points)
    decisions: list[dict[str, Any]] = []
    candidates: list[TradeCandidate] = []
    for idx in range(len(history), len(enriched)):
        row = enriched.iloc[idx]
        source_time = row["timestamp_utc"]
        available = source_time + BAR_DURATION
        decision: dict[str, Any] = {"source_bar_timestamp_utc": source_time.isoformat(),
                                   "available_at_utc": available.isoformat(), "status": "REJECTED", "reason": ""}
        decisions.append(decision)
        if available >= end:
            decision["reason"] = "DECISION_OUTSIDE_WINDOW"
            continue
        if idx < 250:
            decision["reason"] = "INSUFFICIENT_WARMUP"
            continue
        entry_idx = int(enriched["timestamp_utc"].searchsorted(available))
        final_idx = entry_idx + management.max_holding_bars - 1
        if final_idx >= len(enriched) or enriched.iloc[final_idx]["timestamp_utc"] + BAR_DURATION > end:
            decision["reason"] = "INCOMPLETE_EXIT_HORIZON"
            continue
        decision["entry_bar_timestamp_utc"] = enriched.iloc[entry_idx]["timestamp_utc"].isoformat()
        decision["horizon_end_utc"] = (enriched.iloc[final_idx]["timestamp_utc"] + BAR_DURATION).isoformat()
        try:
            snapshot = _snapshot(row, symbol, instrument)
            features = strategy_features_at(enriched, idx, snapshot, max_spread_points=cost_model.max_spread_points)
            signal = evaluate(snapshot, features, params=params)
            decision.update(action=signal.action.value, score=signal.score, strategy_reasons=list(signal.reasons))
            if signal.action == SignalAction.NONE:
                decision["reason"] = "STRATEGY_NONE"
                continue
            sl, tp = build_signal_prices(snapshot, signal.action, float(features["atr"]))
        except ValueError as error:
            decision["reason"] = "INVALID_FEATURES_OR_PROTECTION"
            decision["detail"] = str(error)
            continue
        signal_id = _digest({"evaluation_id": identity_prefix, "symbol": symbol, "source_time": source_time.isoformat()})
        decision.update(status="CANDIDATE", reason="STRATEGY_SIGNAL", signal_id=signal_id)
        candidates.append(TradeCandidate(
            timestamp=source_time, symbol=symbol, direction=Direction(signal.action.value), sl_price=sl, tp_price=tp,
            timeframe="M5", signal_id=signal_id, lot=lot, available_at_utc=available,
            metadata={"strategy_name": STRATEGY_NAME, "strategy_version": STRATEGY_VERSION,
                      "research_evaluator_version": EVALUATOR_VERSION, "effective_params": params.to_dict(),
                      "score": signal.score, "reasons": list(signal.reasons),
                      "regime": features["regime"], "session": features["session"],
                      "full_risk_pipeline_applied": False, "full_pipeline_verified": False,
                      "promotion_eligible": False, "ohlc_price_basis": "MIDPOINT_ASSUMPTION",
                      "horizon_end_utc": decision["horizon_end_utc"]},
        ))
    return CandidateGeneration(tuple(candidates), tuple(decisions))


def _strict_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("unexpected nonfinite research result; refusing successful serialization")
    if isinstance(value, dict):
        return {key: _strict_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_strict_json(item) for item in value]
    return value


def _validated_metrics(outcome: BacktestOutcome) -> tuple[dict[str, Any], str]:
    for trade in outcome.trades:
        _strict_json(asdict(trade))
    for column in ("equity", "balance"):
        if column in outcome.equity_curve and not outcome.equity_curve[column].map(math.isfinite).all():
            raise ValueError("nonfinite equity in research result")
    metrics = asdict(outcome.metrics)
    pf = metrics["profit_factor"]
    status = "FINITE"
    if pf == math.inf and any(x.profit > 0 for x in outcome.trades) and all(x.profit >= 0 for x in outcome.trades):
        metrics["profit_factor"] = None
        status = "UNBOUNDED_NO_LOSSES"
    return _strict_json(metrics), status


@dataclass(frozen=True)
class ResearchEvaluation:
    evaluation_id: str
    status: str
    outcome: BacktestOutcome
    decisions: tuple[dict[str, Any], ...]
    plan_id: str
    hypothesis_id: str
    symbol: str
    split: str

    def to_dict(self) -> dict[str, Any]:
        metrics, pf_status = _validated_metrics(self.outcome)
        return {
            "evaluation_id": self.evaluation_id, "plan_id": self.plan_id, "hypothesis_id": self.hypothesis_id,
            "symbol": self.symbol, "split": self.split, "status": self.status,
            "metrics": metrics, "profit_factor_status": pf_status,
            "denomination_currency": self.outcome.settings.parameters["denomination_currency"],
            "monetary_provenance": self.outcome.settings.parameters["monetary_provenance"],
            "decisions": list(self.decisions), "decision_counts": dict(sorted(Counter(x["reason"] for x in self.decisions).items())),
            "rejected_candidates": list(self.outcome.rejected_candidates), "trades": _strict_json([asdict(x) for x in self.outcome.trades]),
            "full_risk_pipeline_applied": False, "full_pipeline_verified": False, "promotion_eligible": False,
            "scope": "INDEPENDENT_FIXED_LOT_CANDIDATES", "selection_policy": "NONE_COMPARE_ALL",
            "final_holdout": "NOT_AVAILABLE", "walk_forward_status": "NOT_EVALUATED", "baselines_status": "NOT_EVALUATED",
            "model_limitations": ["OHLC interpreted as midpoint; not observed bid/ask ticks", "Entry-bar spread reused for exit pricing; no quote-path spread model", "No portfolio, margin, aggregate risk, swap or currency conversion path", "Realized closed-trade metrics, not mark-to-market account returns", "Costs and instrument provenance are assumptions unless independently verified"],
        }


def evaluate_trend_pullback(plan: ExperimentPlan, candles: pd.DataFrame, *, symbol: str,
                           hypothesis_id: str, split: str) -> ResearchEvaluation:
    """Evaluate one immutable plan cell; persistence/source verification belongs to runner."""
    if not isinstance(plan, ExperimentPlan):
        raise ValueError("ExperimentPlan required")
    payload = plan.to_dict()
    if symbol not in plan.symbols:
        raise ValueError("symbol not in plan")
    hypotheses = {item.hypothesis_id: item for item in plan.hypotheses}
    splits = {item.name: item for item in plan.splits}
    if hypothesis_id not in hypotheses or split not in splits:
        raise ValueError("unknown hypothesis or split")
    bars = normalize_research_bars(candles, symbol=symbol)
    entry = payload["datasets"][symbol]
    if any(entry[key] != value for key, value in _binding(bars, payload["splits"]).items()):
        raise ValueError("dataset hash/rows/splits differ from plan")
    window = splits[split]
    spec, costs = InstrumentSpec(**entry["instrument"]), CostModel(**entry["cost_model"])
    management = ResearchManagement(**payload["management"])
    evaluation_id = _digest({"plan_id": plan.plan_id, "hypothesis_id": hypothesis_id, "symbol": symbol,
                             "split": split, "engine_version": ENGINE_VERSION, "evaluator_version": EVALUATOR_VERSION})
    generation = generate_trend_pullback_candidates(bars, symbol=symbol, params=hypotheses[hypothesis_id].params,
        instrument=spec, cost_model=costs, management=management, lot=payload["lot"],
        window_start=window.start_utc, window_end=window.end_utc, identity_prefix=evaluation_id)
    simulation_bars = bars.loc[(bars["timestamp_utc"] >= _utc(window.start_utc)) &
                               (bars["timestamp_utc"]+BAR_DURATION <= _utc(window.end_utc))].copy()
    settings = BacktestSettings(
        run_id=evaluation_id, strategy_name=STRATEGY_NAME, strategy_version=STRATEGY_VERSION,
        initial_balance=payload["initial_balance"], cost_model=costs,
        break_even_trigger_r=management.break_even_trigger_r, break_even_lock_points=management.break_even_lock_points,
        trailing_start_r=management.trailing_start_r, trailing_distance_points=management.trailing_distance_points,
        max_bars_in_trade=management.max_holding_bars, data_source=entry["data_provenance"]["provider"],
        code_commit=payload["code_commit"], random_seed=payload["random_seed"], data_fingerprint=entry["data_sha256"],
        broker_profile=entry["instrument"], parameters={"plan_id": plan.plan_id, "hypothesis_id": hypothesis_id,
            "strategy_params": hypotheses[hypothesis_id].params.to_dict(), "data_role": payload["data_role"],
            "denomination_currency": payload["denomination_currency"],
            "monetary_provenance": {"tick_value_status": entry["data_provenance"]["tick_value_status"], "cost_status": entry["cost_provenance"]["status"]},
            "full_risk_pipeline_applied": False, "full_pipeline_verified": False, "promotion_eligible": False},
    )
    outcome = Backtester(settings).run(simulation_bars.rename(columns={"timestamp_utc": "timestamp"}), generation.candidates)
    _validated_metrics(outcome)
    status = "COMPLETED" if outcome.trades else "NO_TRADES" if generation.candidates else "NO_CANDIDATES"
    if not any(x.get("action") for x in generation.decisions):
        status = "INSUFFICIENT_DATA"
    return ResearchEvaluation(evaluation_id, status, outcome, generation.decisions, plan.plan_id, hypothesis_id, symbol, split)
