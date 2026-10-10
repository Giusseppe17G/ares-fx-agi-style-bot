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
from ..paper_trading.lifecycle import (PaperAccountObservation, PaperCandidate, PaperCycleInput,
    PaperEvidence, PaperCycleRejected, PaperCycleAuditError, halt_paper_cycle, validate_evidence, validate_quotes)
from ..paper_trading.paper_position_manager import PaperAuditError
from ..telemetry import JsonlAuditLogger, TelemetryDatabase


@dataclass(frozen=True)
class ClosedBarInput:
    symbol: str
    timeframe: str
    bars: pd.DataFrame


# Public transport name retained; temporal semantics are owned by the lifecycle.
ReplayEvidence = PaperEvidence


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
            clock=clock, ml_filter=model_filter, report_dir=str(output / "reports"),
            skip_pre_mutation_failures=False)
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
                cycle = PaperCycleInput(record.event_id, now,
                    PaperAccountObservation(initial_account, now, True), record.quotes,
                    tuple(PaperCandidate(item.symbol, item.timeframe,
                        instrument_snapshot.registry.get(item.symbol).broker_symbol, item.bars)
                        for item in record.decisions), record.evidence)
                result = bot.process_paper_cycle(cycle)
                decisions.extend(result.decisions)
                rejections.extend(result.rejections)
                audit_complete = audit_complete and result.audit_complete
                if result.halted:
                    halted = True
                    break
                valuation = result.valuation
                bot._audit("STATEFUL_EVENT_COMPLETED", Severity.INFO, dict(valuation))
                valuations.append(valuation)
                completed += 1
            except Exception as exc:
                failure = halt_paper_cycle(bot, record.event_id, exc,
                    decisions=decisions[event_decision_start:])
                decisions[event_decision_start:] = failure.decisions
                rejections.extend(failure.rejections)
                audit_complete = audit_complete and failure.audit_complete
                halted = True
                bot.paper_cycle_results.append(failure)
                break
        trades = tuple(_economic_trade(trade.to_dict()) for trade in bot.manager.load_all_trades())
        body = {"decisions": [decision.to_dict() for decision in decisions], "valuations": valuations,
                "rejections": rejections, "trades": list(trades), "events_completed": completed,
                "audit_complete": audit_complete, "halted": halted}
        result = StatefulReplayResult(input_digest, instrument_snapshot.metadata_hash, len(records), completed,
            tuple(decisions), tuple(valuations), tuple(rejections), trades, audit_complete, halted, _digest(body))
        _write_json(output / "result.json", result.to_dict())
        return result


ReplayRejected = PaperCycleRejected
ReplayAuditError = PaperCycleAuditError


def _validate_initial_account(account: AccountState) -> None:
    if not isinstance(account, AccountState) or account.is_demo is not True or account.trade_allowed is not True or str(account.trade_mode).upper() not in {"DEMO", "0"}:
        raise ValueError("initial capital must explicitly belong to a simulated/demo account")
    if account.login is None or not all(_finite(value) and value > 0 for value in (account.balance, account.equity)) or account.balance != account.equity:
        raise ValueError("fresh replay requires finite positive capital and no initial floating equity")


def _validate_market_event(event, config, instrument_snapshot, bot) -> None:
    now = _utc(event.timestamp_utc)
    if instrument_snapshot.captured_at_utc > now:
        raise ReplayRejected("INSTRUMENT_METADATA_FROM_FUTURE", "instrument metadata was unavailable at event time")
    validate_quotes(event.quotes, bot.manager.load_open_trades(), bot.clock.now_utc(), config)
    for symbol, quote in event.quotes.items():
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
    return validate_evidence(value, now, config, has_exposure=has_exposure)


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
