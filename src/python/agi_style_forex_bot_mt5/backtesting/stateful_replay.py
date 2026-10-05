"""Stateful paper replay driven exclusively by explicit chronological quotes.

This adapter owns event scheduling and isolated stores. All strategy, decisions,
capital accounting, position lifecycle and fill logic are production components.
It never calls ForwardShadowBot.run(), a connector, or a broker execution API.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from ..config import BotConfig
from ..contracts import AccountState, MarketSnapshot, Severity
from ..core.clock import FrozenClock
from ..core.decision import PipelineDecision
from ..core.instruments.snapshot import InstrumentRegistrySnapshot
from ..core.safety import SafetyEnvelope
from ..core.run_manifest import RunManifest
from ..core.price_grid import is_price_on_tick_grid
from ..calibration.decision_policy import resolve_signal_profile
from ..data.strategy_features import build_strategy_features
from ..ml import MLFilter
from ..paper_trading import ForwardShadowBot, PaperFillModel
from ..paper_trading.decision_state import capture_paper_daily_reference
from ..paper_trading.paper_position_manager import PaperAuditError
from ..telemetry import JsonlAuditLogger, TelemetryDatabase


@dataclass(frozen=True)
class ClosedBarInput:
    symbol: str
    timeframe: str
    bars: pd.DataFrame


@dataclass(frozen=True)
class ReplayEvidence:
    observed_at_utc: datetime
    broker_readiness_score: float
    correlation: float | None


@dataclass(frozen=True)
class StatefulReplayEvent:
    event_id: str
    timestamp_utc: datetime
    quotes: Mapping[str, MarketSnapshot]
    decisions: tuple[ClosedBarInput, ...]
    evidence: Mapping[str, ReplayEvidence]


@dataclass(frozen=True)
class StatefulReplayResult:
    input_digest: str
    metadata_hash: str
    events_total: int
    events_completed: int
    decisions: tuple[PipelineDecision, ...]
    valuations: tuple[Mapping[str, Any], ...]
    rejections: tuple[Mapping[str, Any], ...]
    trades: tuple[Mapping[str, Any], ...]
    audit_complete: bool
    halted: bool
    result_digest: str

    def to_dict(self) -> dict[str, Any]:
        return SafetyEnvelope().seal({
            "scope": "STATEFUL_EXPLICIT_QUOTE_REPLAY", "input_digest": self.input_digest,
            "metadata_hash": self.metadata_hash, "events_total": self.events_total,
            "events_completed": self.events_completed,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "valuations": list(self.valuations), "rejections": list(self.rejections),
            "trades": list(self.trades), "audit_complete": self.audit_complete,
            "halted": self.halted, "result_digest": self.result_digest,
            "full_pipeline_verified": False, "performance_promoted": False,
            "execution_authorized": False, "intrabar_prices_invented": False,
            "ranking_scope": "SEQUENTIAL_SINGLE_CANDIDATE",
            "metadata_authenticity_verified": False,
            "limitations": ["Explicit observed quote path only; unobserved intrabar paths are unknown",
                "Shared paper lifecycle simulation is not evidence of broker fill equivalence",
                "Instrument hashes verify content consistency, not origin or authenticity"],
        }, full=True)


def run_stateful_replay(
    events: Iterable[StatefulReplayEvent], *, config: BotConfig,
    initial_account: AccountState, instrument_snapshot: InstrumentRegistrySnapshot,
    output_dir: str | Path, model_filter: MLFilter, fill_model: PaperFillModel,
) -> StatefulReplayResult:
    """Replay a fresh explicitly funded paper book; never import a supplied book.

    Quotes are required for every open position at every event. A missing or
    invalid market event halts further processing; absent candidate evidence
    rejects that candidate. New-day overnight equity requires an event exactly
    at midnight UTC with exact boundary quotes. No bar high/low becomes a tick.
    """
    config.validate_safety()
    SafetyEnvelope.from_config(config).require_paper_only(context="stateful replay")
    if not isinstance(model_filter, MLFilter) or not isinstance(fill_model, PaperFillModel):
        raise ValueError("replay requires explicit MLFilter and PaperFillModel instances")
    if not isinstance(instrument_snapshot, InstrumentRegistrySnapshot):
        raise ValueError("an observed instrument metadata snapshot is required")
    _validate_initial_account(initial_account)
    if fill_model.max_spread_points > config.max_spread_points_default or fill_model.max_tick_age_seconds > config.max_tick_age_seconds:
        raise ValueError("fill assumptions must not weaken configured spread/freshness limits")
    records = tuple(events)
    if not records:
        raise ValueError("stateful replay requires at least one explicit market event")
    payloads = [_event_payload(record) for record in records]
    input_digest = _digest(payloads)
    start = _utc(records[0].timestamp_utc)
    clock = FrozenClock(start)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("stateful replay output directory must be new or empty")
    # Exclusive creation also serializes two concurrent attempts at an empty dir.
    with (output / "replay.lock").open("x", encoding="utf-8") as handle:
        handle.write(input_digest)
        handle.flush()
        os.fsync(handle.fileno())
    _write_jsonl(output / "inputs.jsonl", payloads)
    instrument_snapshot.write(output / "instruments.json")
    manifest = _manifest(config, initial_account, instrument_snapshot, model_filter, fill_model, input_digest, clock)
    _write_json(output / "manifest.json", manifest)
    decisions: list[PipelineDecision] = []
    valuations: list[Mapping[str, Any]] = []
    rejections: list[Mapping[str, Any]] = []
    identities: set[str] = set()
    previous: datetime | None = None
    completed = 0
    audit_complete = True
    halted = False
    with closing(TelemetryDatabase(output / "replay.sqlite3")) as database:
        bot = ForwardShadowBot(config=config, symbols=instrument_snapshot.registry.symbols(),
            audit_logger=JsonlAuditLogger(output / "events"), database=database,
            clock=clock, ml_filter=model_filter, report_dir=str(output / "reports"))
        bot.run_id = manifest["run_manifest"]["run_id"]
        bot.manager.fill_model = replace(fill_model, clock=clock)
        for record, payload in zip(records, payloads):
            event_decision_start = len(decisions)
            try:
                now = _utc(record.timestamp_utc)
                if previous is not None and now < previous:
                    raise ReplayRejected("EVENT_TIME_REVERSED", "market events must be chronological")
                if not isinstance(record.event_id, str) or not record.event_id or record.event_id in identities:
                    raise ReplayRejected("EVENT_ID_INVALID", "market event identities must be nonempty and unique")
                identities.add(record.event_id)
                previous = now
                clock.instant = now
                bot._audit("STATEFUL_EVENT_RECEIVED", Severity.INFO,
                           {"event_id": record.event_id, "input_event_digest": _digest(payload), "timestamp_utc": now.isoformat()})
                _validate_market_event(record, config, instrument_snapshot, bot)
                # Snapshot lifecycle is exactly the same method used by forward.
                for trade in bot.manager.load_open_trades():
                    updated = bot.manager.update_with_snapshot(trade, record.quotes[trade.symbol])
                    if updated.status == "CLOSED":
                        bot._audit("PAPER_TRADE_CLOSED", Severity.INFO, updated.to_dict(), symbol=updated.symbol)
                if now.time() == datetime.min.time():
                    capture_paper_daily_reference(database=database, trades=bot.manager.load_all_trades(),
                        snapshots_by_symbol=record.quotes, account_template=initial_account, now_utc=now,
                        max_snapshot_age_seconds=config.max_market_snapshot_age_seconds,
                        max_daily_drawdown_pct=config.max_daily_drawdown_pct)
                bot._refresh_paper_risk_state(initial_account, snapshots=record.quotes)
                candidate_ids: set[tuple[str, str]] = set()
                for candidate in record.decisions:
                    key = (candidate.symbol, candidate.timeframe)
                    if key in candidate_ids:
                        raise ReplayRejected("DUPLICATE_EVENT_CANDIDATE", "a symbol/timeframe may be evaluated once per event")
                    candidate_ids.add(key)
                    try:
                        quote = record.quotes.get(candidate.symbol)
                        if quote is None:
                            raise ReplayRejected("CANDIDATE_QUOTE_MISSING", "candidate has no explicit quote")
                        snapshot = replace(quote, timeframe=candidate.timeframe)
                        evidence = _evidence(record.evidence.get(candidate.symbol), now, config,
                                             has_exposure=bool(bot.manager.load_open_trades()))
                        features = build_strategy_features(candidate.bars, snapshot,
                                                           max_spread_points=config.max_spread_points_default)
                        features.update(broker_readiness_score=evidence.broker_readiness_score,
                                        correlation=evidence.correlation)
                        spec = instrument_snapshot.registry.get(candidate.symbol)
                        context = bot._paper_decision_context(snapshot, features, initial_account,
                                                              spec.broker_symbol, snapshots=record.quotes)
                        if bot._paper_signal_already_traded(context.decision_id, candidate.symbol):
                            rejections.append({"event_id": record.event_id, "symbol": candidate.symbol,
                                "reject_code": "CANDIDATE_ALREADY_TRADED", "fatal": False})
                            continue
                        decision = bot._evaluate_paper_decision(context)
                        decisions.append(decision)
                        if any(stage.stage_id == "signal_audit" and stage.status in {"error", "rejected"} for stage in decision.trace):
                            audit_complete = False
                            raise ReplayAuditError("signal persistence was not confirmed")
                        if not decision.accepted:
                            rejections.append({"event_id": record.event_id, "symbol": candidate.symbol,
                                "reject_code": decision.reject_code, "fatal": False})
                            continue
                        assert decision.trade_signal is not None and decision.risk_decision is not None and decision.strategy_signal is not None
                        before = database.count_rows("paper_trades")
                        strategy = decision.strategy_signal
                        trade = bot.manager.open_trade(signal=decision.trade_signal,
                            risk_decision=decision.risk_decision, snapshot=snapshot,
                            broker_symbol=spec.broker_symbol, score=strategy.score,
                            reasons=strategy.reasons, strategy_name=strategy.strategy_name,
                            strategy_version=decision.trade_signal.strategy_version,
                            regime=str(features["regime"]), session=str(features["session"]))
                        trade = bot._decorate_stable_trade(trade, strategy, features)
                        if database.count_rows("paper_trades") > before:
                            bot._audit("PAPER_TRADE_OPENED", Severity.INFO, trade.to_dict(), symbol=trade.symbol)
                        bot._refresh_paper_risk_state(initial_account, snapshots=record.quotes)
                    except ReplayRejected as exc:
                        rejected = {"event_id": record.event_id, "symbol": candidate.symbol,
                                    "reject_code": exc.code, "reason": exc.reason, "fatal": False}
                        bot._audit("STATEFUL_CANDIDATE_REJECTED", Severity.WARNING, rejected, symbol=candidate.symbol)
                        rejections.append(rejected)
                    # Unexpected/data/storage failures abort rather than skip an
                    # unknown lifecycle or carry an unconfirmed acceptance.
                state = bot._refresh_paper_risk_state(initial_account, snapshots=record.quotes)
                valuation = {"event_id": record.event_id, "timestamp_utc": now.isoformat(),
                    "balance": state.account.balance, "equity": state.account.equity,
                    "realized_pnl": state.realized_pnl, "floating_pnl": state.floating_pnl,
                    "open_positions": len(state.risk_state.open_positions),
                    "open_risk_amount": sum(state.risk_state.open_position_risk_amounts.values()),
                    "daily_reference": state.risk_state.daily_equity_reference,
                    "daily_halted": state.risk_state.kill_switch.active}
                bot._audit("STATEFUL_EVENT_COMPLETED", Severity.INFO, valuation)
                valuations.append(valuation)
                completed += 1
            except Exception as exc:
                code = getattr(exc, "code", None) or getattr(exc, "detail", {}).get("reject_code") or "STATEFUL_EVENT_ERROR"
                rejection = {"event_id": record.event_id, "reject_code": code,
                             "error_type": type(exc).__name__, "fatal": True}
                rejections.append(rejection)
                halted = True
                if isinstance(exc, (OSError, sqlite3.Error, ReplayAuditError, PaperAuditError)) or getattr(bot, "audit_failed", False):
                    audit_complete = False
                try:
                    bot._audit("STATEFUL_REPLAY_HALTED", Severity.ERROR, rejection)
                except Exception:
                    audit_complete = False
                # A decision whose storage/fill lifecycle failed must not remain
                # usable as approval in the returned replay result.
                for index in range(event_decision_start, len(decisions)):
                    last = decisions[index]
                    if not last.accepted:
                        continue
                    risk = last.risk_decision
                    if risk is not None:
                        risk = replace(risk, accepted=False, approved_lot=0.0, risk_amount_account_currency=0.0,
                                       reject_code="REPLAY_EVENT_ABORTED", reject_reason="replay event did not complete")
                    decisions[index] = replace(last, accepted=False, reject_code="REPLAY_EVENT_ABORTED",
                                           reject_reason="replay event did not complete", risk_decision=risk)
                break
        trades = tuple(_economic_trade(trade.to_dict()) for trade in bot.manager.load_all_trades())
        body = {"decisions": [decision.to_dict() for decision in decisions], "valuations": valuations,
                "rejections": rejections, "trades": list(trades), "events_completed": completed,
                "audit_complete": audit_complete, "halted": halted}
        result = StatefulReplayResult(input_digest, instrument_snapshot.metadata_hash, len(records), completed,
            tuple(decisions), tuple(valuations), tuple(rejections), trades, audit_complete, halted, _digest(body))
        _write_json(output / "result.json", result.to_dict())
        return result


class ReplayRejected(ValueError):
    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code, self.reason = code, reason


class ReplayAuditError(RuntimeError):
    code = "DECISION_AUDIT_FAILED"


def _validate_initial_account(account: AccountState) -> None:
    if not isinstance(account, AccountState) or account.is_demo is not True or account.trade_allowed is not True or str(account.trade_mode).upper() not in {"DEMO", "0"}:
        raise ValueError("initial capital must explicitly belong to a simulated/demo account")
    if account.login is None or not all(_finite(value) and value > 0 for value in (account.balance, account.equity)) or account.balance != account.equity:
        raise ValueError("fresh replay requires finite positive capital and no initial floating equity")


def _validate_market_event(event, config, instrument_snapshot, bot) -> None:
    now = _utc(event.timestamp_utc)
    if instrument_snapshot.captured_at_utc > now:
        raise ReplayRejected("INSTRUMENT_METADATA_FROM_FUTURE", "instrument metadata was unavailable at event time")
    if not event.quotes:
        raise ReplayRejected("EVENT_QUOTES_MISSING", "every market event needs explicit quotes")
    for symbol, quote in event.quotes.items():
        if not isinstance(quote, MarketSnapshot) or quote.symbol != symbol:
            raise ReplayRejected("QUOTE_SYMBOL_MISMATCH", "quote does not match its symbol key")
        quote.validate()
        age = (now - _utc(quote.timestamp_utc)).total_seconds()
        if not 0 <= age <= min(config.max_tick_age_seconds, config.max_market_snapshot_age_seconds):
            raise ReplayRejected("QUOTE_TIME_INVALID", "quote is stale or from the future")
        if not all(_finite(getattr(quote, field)) for field in ("bid", "ask", "spread_points")):
            raise ReplayRejected("QUOTE_INVALID", "quote values must be finite")
        if not all(is_price_on_tick_grid(getattr(quote, field), quote.tick_size) for field in ("bid", "ask")):
            raise ReplayRejected("QUOTE_GRID_INVALID", "observed quote is outside the instrument tick grid")
        actual_spread = (quote.ask - quote.bid) / quote.point
        if not math.isclose(actual_spread, quote.spread_points, rel_tol=0, abs_tol=1e-6):
            raise ReplayRejected("QUOTE_SPREAD_MISMATCH", "quote spread must agree with bid/ask")
        spec = instrument_snapshot.registry.get(symbol)
        for quote_field, spec_field in (("digits", "digits"), ("point", "point"),
            ("tick_size", "tick_size"), ("tick_value", "tick_value"), ("volume_min", "min_volume"),
            ("volume_max", "max_volume"), ("volume_step", "volume_step"),
            ("stops_level_points", "stops_level_points"), ("freeze_level_points", "freeze_level_points")):
            if getattr(quote, quote_field) != getattr(spec, spec_field):
                raise ReplayRejected("QUOTE_METADATA_MISMATCH", "quote differs from frozen instrument metadata")
    for trade in bot.manager.load_open_trades():
        if trade.symbol not in event.quotes:
            raise ReplayRejected("OPEN_POSITION_QUOTE_MISSING", "an open position has no explicit event quote")


def _evidence(value, now, config, *, has_exposure):
    if not isinstance(value, ReplayEvidence):
        raise ReplayRejected("BROKER_EVIDENCE_MISSING", "candidate requires explicit broker quality evidence")
    age = (now - _utc(value.observed_at_utc)).total_seconds()
    if not 0 <= age <= config.max_market_snapshot_age_seconds:
        raise ReplayRejected("BROKER_EVIDENCE_TIME_INVALID", "quality evidence is stale or from the future")
    if not _finite(value.broker_readiness_score) or not 0 < value.broker_readiness_score <= 100:
        raise ReplayRejected("BROKER_QUALITY_UNVERIFIED", "broker readiness score is invalid")
    if (has_exposure and value.correlation is None) or (value.correlation is not None and
            (not _finite(value.correlation) or not -1 <= value.correlation <= 1)):
        raise ReplayRejected("CORRELATION_UNVERIFIED", "exposed book requires measured finite correlation")
    return value


def _manifest(config, initial, instruments, model, fill, input_digest, clock):
    configuration = asdict(config)
    for key in ("allowed_account_logins", "profile_config", "paper_risk_clearance", "paper_daily_risk_ledger"):
        configuration.pop(key, None)
    profile_hash = hashlib.sha256(Path(config.profile_config).read_bytes()).hexdigest() if config.profile_config else None
    # Explicit injected object only; no discovery of data/models or other runs.
    model_digest = hashlib.sha256(pickle.dumps(model.bundle)).hexdigest() if model.bundle is not None else None
    effective = {"schema_version": "1.0", "scope": "STATEFUL_EXPLICIT_QUOTE_REPLAY",
        "input_digest": input_digest, "config": configuration, "profile_content_hash": profile_hash,
        "effective_signal_profile": resolve_signal_profile(config),
        "initial_balance": initial.balance, "currency": initial.currency,
        "metadata_hash": instruments.metadata_hash, "metadata_snapshot_hash": instruments.snapshot_hash,
        "model_bundle_digest": model_digest,
        "model_thresholds": {key: getattr(model, key) for key in
            ("minimum_probability_for_shadow_trade", "high_quality_threshold", "reject_below")},
        "fill_assumptions": {key: value for key, value in asdict(fill).items() if key != "clock"},
        "full_pipeline_verified": False, "performance_promoted": False,
        **SafetyEnvelope().as_dict()}
    manifest = RunManifest.build(mode="stateful_explicit_quote_replay", clock=clock,
        config=effective, dataset_hash=input_digest, symbols=instruments.registry.symbols(),
        instrument_snapshot_hash=instruments.snapshot_hash, instrument_metadata_hash=instruments.metadata_hash)
    return {**effective, "run_manifest": manifest.as_dict()}


def _event_payload(event):
    return {"event_id": event.event_id, "timestamp_utc": event.timestamp_utc,
        "quotes": {key: asdict(value) for key, value in event.quotes.items()},
        "decisions": [{"symbol": item.symbol, "timeframe": item.timeframe,
                       "bars": item.bars.to_dict(orient="records")} for item in event.decisions],
        "evidence": {key: asdict(value) for key, value in event.evidence.items()}}


def _economic_trade(payload):
    value = dict(payload)
    value.pop("paper_trade_id", None)
    return value


def _utc(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ReplayRejected("TIMESTAMP_INVALID", "event timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError("replay input is not JSON serializable")


def _json(value):
    return json.dumps(value, default=_default, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _write_json(path, payload):
    _write_jsonl(path, (payload,))


def _write_jsonl(path, rows):
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
