"""One economic paper lifecycle for observed forward cycles and quote replay.

Acquisition is owned by callers. This module never fetches missing quotes or
freezes the operational clock: every freshness check reads the injected clock.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

import pandas as pd

from ..contracts import AccountState, MarketSnapshot, Severity, SignalAction
from ..core.decision import PipelineDecision
from ..core.price_grid import is_price_on_tick_grid, spread_points_from_prices
from ..data.strategy_features import build_strategy_features
from .decision_state import capture_paper_daily_reference
from .paper_position_manager import PaperAuditError


@dataclass(frozen=True)
class PaperAccountObservation:
    account: AccountState | None
    observed_at_utc: datetime
    connected: bool | None


@dataclass(frozen=True)
class PaperCandidate:
    symbol: str
    timeframe: str
    broker_symbol: str
    bars: pd.DataFrame
    features: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PaperEvidence:
    observed_at_utc: datetime
    broker_readiness_score: float
    correlation: float | None


@dataclass(frozen=True)
class PaperCycleInput:
    event_id: str
    observed_at_utc: datetime
    account_observation: PaperAccountObservation
    quotes: Mapping[str, MarketSnapshot]
    candidates: tuple[PaperCandidate, ...]
    evidence: Mapping[str, PaperEvidence]


@dataclass(frozen=True)
class PaperCycleResult:
    event_id: str
    decisions: tuple[PipelineDecision, ...]
    rejections: tuple[Mapping[str, Any], ...]
    valuation: Mapping[str, Any] | None
    trades: tuple[Mapping[str, Any], ...]
    opened: int
    closed: int
    paused: bool
    halted: bool
    audit_complete: bool

    def to_dict(self):
        return {"event_id": self.event_id, "decisions": [item.to_dict() for item in self.decisions],
            "rejections": list(self.rejections), "valuation": self.valuation, "trades": list(self.trades),
            "opened": self.opened, "closed": self.closed, "paused": self.paused,
            "halted": self.halted, "audit_complete": self.audit_complete,
            "execution_authorized": False, "full_pipeline_verified": False}


class PaperCycleRejected(ValueError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code, self.reason = code, reason


class PaperCycleAuditError(RuntimeError):
    code = "DECISION_AUDIT_FAILED"


def utc(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise PaperCycleRejected("TIMESTAMP_INVALID", "observations require timezone-aware timestamps")
    return value.astimezone(timezone.utc)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_evidence(value, now, config, *, has_exposure):
    if isinstance(value, Mapping):
        try:
            value = PaperEvidence(value["observed_at_utc"], value["broker_readiness_score"], value.get("correlation"))
        except KeyError:
            value = None
    if not isinstance(value, PaperEvidence):
        raise PaperCycleRejected("BROKER_EVIDENCE_MISSING", "candidate requires dated broker quality evidence")
    age = (utc(now) - utc(value.observed_at_utc)).total_seconds()
    if not 0 <= age <= config.max_market_snapshot_age_seconds:
        raise PaperCycleRejected("BROKER_EVIDENCE_TIME_INVALID", "quality evidence is stale or from the future")
    if not finite(value.broker_readiness_score) or not 0 < value.broker_readiness_score <= 100:
        raise PaperCycleRejected("BROKER_QUALITY_UNVERIFIED", "broker readiness score is invalid")
    if (has_exposure and value.correlation is None) or (value.correlation is not None and
            (not finite(value.correlation) or not -1 <= value.correlation <= 1)):
        raise PaperCycleRejected("CORRELATION_UNVERIFIED", "exposed book requires measured finite correlation")
    return value


def validate_quotes(quotes, open_trades, now, config):
    if not quotes:
        raise PaperCycleRejected("EVENT_QUOTES_MISSING", "cycle needs explicit market quotes")
    for symbol, quote in quotes.items():
        if not isinstance(quote, MarketSnapshot) or quote.symbol != symbol:
            raise PaperCycleRejected("QUOTE_SYMBOL_MISMATCH", "quote does not match its symbol key")
        numeric = ("bid", "ask", "spread_points", "point", "tick_value", "tick_size",
                   "volume_min", "volume_max", "volume_step", "digits", "stops_level_points", "freeze_level_points")
        if not all(finite(getattr(quote, field)) for field in numeric):
            raise PaperCycleRejected("QUOTE_INVALID", "quote and instrument values must be finite")
        if any(type(getattr(quote, field)) is not int or getattr(quote, field) < 0
               for field in ("digits", "stops_level_points", "freeze_level_points")):
            raise PaperCycleRejected("QUOTE_METADATA_INVALID", "precision and stop levels must be nonnegative integers")
        quote.validate()
        age = (utc(now) - utc(quote.timestamp_utc)).total_seconds()
        if not 0 <= age <= min(config.max_tick_age_seconds, config.max_market_snapshot_age_seconds):
            raise PaperCycleRejected("QUOTE_TIME_INVALID", "quote is stale or from the future")
        if not all(finite(getattr(quote, field)) for field in ("bid", "ask", "spread_points")):
            raise PaperCycleRejected("QUOTE_INVALID", "quote values must be finite")
        if not all(is_price_on_tick_grid(getattr(quote, field), quote.tick_size) for field in ("bid", "ask")):
            raise PaperCycleRejected("QUOTE_GRID_INVALID", "observed quote is outside the instrument tick grid")
        if not math.isclose(spread_points_from_prices(quote.bid, quote.ask, quote.point), quote.spread_points, rel_tol=0, abs_tol=1e-6):
            raise PaperCycleRejected("QUOTE_SPREAD_MISMATCH", "quote spread must agree with bid/ask")
    for trade in open_trades:
        if trade.symbol not in quotes:
            raise PaperCycleRejected("OPEN_POSITION_QUOTE_MISSING", "open position has no explicit cycle quote")


def validate_account(observation, now, config):
    if not isinstance(observation, PaperAccountObservation):
        raise PaperCycleRejected("ACCOUNT_OBSERVATION_MISSING", "cycle requires an account observation")
    age = (utc(now)-utc(observation.observed_at_utc)).total_seconds()
    if not 0 <= age <= config.max_market_snapshot_age_seconds:
        raise PaperCycleRejected("ACCOUNT_OBSERVATION_STALE", "account observation is stale or future")
    account = observation.account
    if not isinstance(account, AccountState):
        raise PaperCycleRejected("ACCOUNT_INFO_UNAVAILABLE", "complete account observation is required")
    if observation.connected is not True:
        raise PaperCycleRejected("MT5_CONNECTION_UNVERIFIED", "connection is not explicitly confirmed")
    if account.is_demo is not True or str(account.trade_mode).upper() not in {"DEMO", "0"}:
        raise PaperCycleRejected("ACCOUNT_REAL_DETECTED_READ_ONLY", "known demo account required for this release")
    if (type(account.login) is not int or account.login <= 0 or not isinstance(account.currency, str)
            or len(account.currency) != 3 or not account.currency.isascii() or not account.currency.isalpha()):
        raise PaperCycleRejected("ACCOUNT_INFO_INVALID", "account identity and currency are required")
    if not all(finite(value) and value > 0 for value in (account.balance, account.equity)) or not finite(account.margin_free) or account.margin_free < 0 or account.trade_allowed is not True:
        raise PaperCycleRejected("ACCOUNT_INFO_INVALID", "account capital or permissions are invalid")
    return account


def economic_trade(trade):
    payload = trade.to_dict() if hasattr(trade, "to_dict") else dict(trade)
    payload.pop("paper_trade_id", None)
    return payload


def _sync_daily_pause(bot, state):
    runtime = bot.database.get_operational_state()
    if state.risk_state.kill_switch.active:
        if not runtime.get("shadow_paused") or (runtime.get("paused_reason") == "PAPER_DAILY_DRAWDOWN_HALT" and runtime.get("paused_by") == "paper_lifecycle"):
            bot.database.set_shadow_paused(True, reason="PAPER_DAILY_DRAWDOWN_HALT", paused_by="paper_lifecycle")
        bot.database.update_operational_state({"paper_daily_halt_day": state.operational_day})
    # A manual or unknown pause never expires here. Daily risk references and
    # the ledger's own latch must already have validated the new day.
    runtime = bot.database.get_operational_state()
    if (runtime.get("paused_reason") == "PAPER_DAILY_DRAWDOWN_HALT"
            and runtime.get("paused_by") == "paper_lifecycle"
            and str(runtime.get("paper_daily_halt_day", "")) < state.operational_day
            and bot.config.manual_resume_required is False
            and not state.risk_state.kill_switch.active):
        bot.database.set_shadow_paused(False, reason="verified next UTC day", paused_by="paper_lifecycle")


def process_paper_cycle(bot, cycle: PaperCycleInput) -> PaperCycleResult:
    """Process one supplied market cycle, latching any uncertain lifecycle.

    Strategy rejections may continue to the next candidate. Storage, audit,
    acquisition/account and position-management failures stop the entire run.
    Persisted fills remain reported if a later audit fails; approval is revoked.
    """
    decisions, rejections = [], []
    opened = closed = 0
    valuation = None
    intent_written = False
    try:
        runtime = bot.database.get_operational_state()
        if getattr(bot, "paper_lifecycle_halted", False) or getattr(bot, "audit_failed", False) or runtime.get("paper_lifecycle_halted") or runtime.get("paper_cycle_in_progress"):
            raise PaperCycleRejected("PAPER_LIFECYCLE_HALTED", "previous uncertain lifecycle requires reconciliation")
        now = utc(bot.clock.now_utc())
        event_time = utc(cycle.observed_at_utc)
        if not 0 <= (now-event_time).total_seconds() <= bot.config.max_market_snapshot_age_seconds:
            raise PaperCycleRejected("EVENT_TIME_INVALID", "cycle acquisition is stale or future")
        previous = getattr(bot, "_paper_previous_cycle_time", None)
        seen = getattr(bot, "_paper_cycle_ids", set())
        if previous is not None and event_time < previous:
            raise PaperCycleRejected("EVENT_TIME_REVERSED", "cycle time reversed")
        if not cycle.event_id or cycle.event_id in seen:
            raise PaperCycleRejected("EVENT_ID_INVALID", "cycle identities must be unique")
        bot._paper_previous_cycle_time = event_time
        bot._paper_cycle_ids = seen | {cycle.event_id}
        account = validate_account(cycle.account_observation, now, bot.config)
        identity = (account.login, account.currency)
        if getattr(bot, "_paper_account_identity", identity) != identity:
            raise PaperCycleRejected("ACCOUNT_CHANGED", "account identity changed during observation")
        bot._paper_account_identity = identity
        bot._audit("PAPER_CYCLE_RECEIVED", Severity.INFO, {"event_id": cycle.event_id,
            "timestamp_utc": event_time.isoformat(), "execution_attempted": False})
        validate_quotes(cycle.quotes, bot.manager.load_open_trades(), bot.clock.now_utc(), bot.config)
        # Write intent BEFORE any financial mutation. A crash or inaccessible
        # store after fill cannot become an apparently clean restart.
        bot.database.update_operational_state({"paper_cycle_in_progress": cycle.event_id})
        intent_written = True
        for trade in bot.manager.load_open_trades():
            # Recheck against the live clock immediately before every mutation.
            validate_quotes(cycle.quotes, bot.manager.load_open_trades(), bot.clock.now_utc(), bot.config)
            updated = bot.manager.update_with_snapshot(trade, cycle.quotes[trade.symbol])
            if updated.status == "CLOSED":
                closed += 1
                bot._audit("PAPER_TRADE_CLOSED", Severity.INFO, updated.to_dict(), symbol=updated.symbol, notify=True)
        if event_time.time() == datetime.min.time():
            capture_paper_daily_reference(database=bot.database, trades=bot.manager.load_all_trades(),
                snapshots_by_symbol=cycle.quotes, account_template=account, now_utc=bot.clock.now_utc(),
                max_snapshot_age_seconds=bot.config.max_market_snapshot_age_seconds,
                max_daily_drawdown_pct=bot.config.max_daily_drawdown_pct)
        state = bot._refresh_paper_risk_state(account, snapshots=cycle.quotes)
        _sync_daily_pause(bot, state)
        candidate_ids = set()
        for candidate in cycle.candidates:
            key = (candidate.symbol, candidate.timeframe)
            if key in candidate_ids:
                raise PaperCycleRejected("DUPLICATE_EVENT_CANDIDATE", "one symbol/timeframe candidate per cycle")
            candidate_ids.add(key)
            decision = None
            validate_account(cycle.account_observation, bot.clock.now_utc(), bot.config)
            validate_quotes(cycle.quotes, bot.manager.load_open_trades(), bot.clock.now_utc(), bot.config)
            try:
                quote = cycle.quotes.get(candidate.symbol)
                if quote is None:
                    raise PaperCycleRejected("CANDIDATE_QUOTE_MISSING", "candidate has no observed quote")
                snapshot = replace(quote, timeframe=candidate.timeframe)
                features = dict(candidate.features) if candidate.features is not None else build_strategy_features(candidate.bars, snapshot, max_spread_points=bot.config.max_spread_points_default)
                state = bot._refresh_paper_risk_state(account, snapshots=cycle.quotes)
                value = cycle.evidence.get(candidate.symbol)
                if value is None and bot.decision_evidence_provider is not None:
                    value = bot.decision_evidence_provider(snapshot, features, state.portfolio_open_trades)
                evidence = validate_evidence(value, bot.clock.now_utc(), bot.config, has_exposure=bool(state.risk_state.open_positions))
                context = bot._paper_decision_context(snapshot, features, account, candidate.broker_symbol,
                    snapshots=cycle.quotes, evidence=evidence)
                if bot._paper_signal_already_traded(context.decision_id, candidate.symbol):
                    raise PaperCycleRejected("CANDIDATE_ALREADY_TRADED", "closed-bar/profile identity already has a paper trade")
                decision = bot._evaluate_paper_decision(context)
                decisions.append(decision)
                if getattr(bot, "audit_failed", False) or any(stage.stage_id == "signal_audit" and stage.status in {"error", "rejected"} for stage in decision.trace):
                    raise PaperCycleAuditError("signal persistence was not confirmed")
                strategy = decision.strategy_signal
                if strategy is not None:
                    payload = bot._forward_candidate_payload(candidate.symbol, strategy, features)
                    payload["signal_id"] = context.decision_id
                    bot._audit("FORWARD_CANDIDATE_EVALUATED", Severity.INFO, payload, symbol=candidate.symbol)
                    if strategy.action == SignalAction.NONE:
                        bot._audit("FORWARD_CANDIDATE_BLOCKED", Severity.INFO, payload, symbol=candidate.symbol)
                        if payload.get("near_miss"):
                            bot._audit("FORWARD_NEAR_MISS", Severity.INFO, payload, symbol=candidate.symbol)
                if not decision.accepted:
                    bot._audit("SIGNAL_REJECTED", Severity.WARNING, decision.to_dict(), symbol=candidate.symbol)
                    raise PaperCycleRejected(decision.reject_code, decision.reject_reason)
                validate_quotes(cycle.quotes, bot.manager.load_open_trades(), bot.clock.now_utc(), bot.config)
                validate_account(cycle.account_observation, bot.clock.now_utc(), bot.config)
                validate_evidence(evidence, bot.clock.now_utc(), bot.config, has_exposure=bool(state.risk_state.open_positions))
                before = bot.database.count_rows("paper_trades")
                trade = bot.manager.open_trade(signal=decision.trade_signal, risk_decision=decision.risk_decision,
                    snapshot=snapshot, broker_symbol=candidate.broker_symbol, score=strategy.score,
                    reasons=strategy.reasons, strategy_name=strategy.strategy_name,
                    strategy_version=decision.trade_signal.strategy_version,
                    regime=str(features["regime"]), session=str(features["session"]))
                trade = bot._decorate_stable_trade(trade, strategy, features)
                if bot.database.count_rows("paper_trades") > before:
                    opened += 1
                    bot._audit("PAPER_TRADE_OPENED", Severity.INFO, trade.to_dict(), symbol=trade.symbol, notify=True)
                state = bot._refresh_paper_risk_state(account, snapshots=cycle.quotes)
                _sync_daily_pause(bot, state)
            except PaperCycleRejected as exc:
                if decision is not None and decision.accepted:
                    raise
                payload = {"event_id": cycle.event_id, "symbol": candidate.symbol,
                    "reject_code": exc.code, "reason": exc.reason, "fatal": False}
                bot._audit("PAPER_CANDIDATE_REJECTED", Severity.WARNING, payload, symbol=candidate.symbol)
                rejections.append(payload)
        state = bot._refresh_paper_risk_state(account, snapshots=cycle.quotes)
        _sync_daily_pause(bot, state)
        valuation = {"event_id": cycle.event_id, "timestamp_utc": event_time.isoformat(),
            "balance": state.account.balance, "equity": state.account.equity,
            "realized_pnl": state.realized_pnl, "floating_pnl": state.floating_pnl,
            "open_positions": len(state.risk_state.open_positions),
            "open_risk_amount": sum(state.risk_state.open_position_risk_amounts.values()),
            "daily_reference": state.risk_state.daily_equity_reference,
            "daily_halted": state.risk_state.kill_switch.active,
            "shadow_paused": bot.database.get_shadow_paused()}
        result = PaperCycleResult(cycle.event_id, tuple(decisions), tuple(rejections), valuation,
            tuple(economic_trade(trade) for trade in bot.manager.load_all_trades()), opened, closed,
            bot.database.get_shadow_paused(), False, True)
        bot._audit("PAPER_CYCLE_COMPLETED", Severity.INFO, result.to_dict())
        bot.database.update_operational_state({"paper_cycle_in_progress": None})
    except Exception as exc:
        if not intent_written and skippable_before_mutation(bot, exc):
            result = skip_paper_cycle(bot, cycle.event_id, exc)
        else:
            result = halt_paper_cycle(bot, cycle.event_id, exc, decisions=decisions,
                rejections=rejections, opened=opened, closed=closed)
    bot.paper_cycle_results.append(result)
    return result


# Operational conditions seen before a cycle writes its intent: the paper book
# is untouched, so a live run may audit, back off and retry instead of latching.
# Replay keeps the latch: a recorded event without quotes is an input defect
# there, not a closed market. Account, integrity and storage failures always latch.
SKIPPABLE_BEFORE_MUTATION = frozenset({
    "MT5_CONNECT_FAILED", "MT5_CONNECTION_UNVERIFIED", "ACCOUNT_INFO_UNAVAILABLE",
    "ACCOUNT_OBSERVATION_STALE", "EVENT_TIME_INVALID", "EVENT_QUOTES_MISSING",
    "QUOTE_TIME_INVALID", "OPEN_POSITION_QUOTE_MISSING",
})


def skippable_before_mutation(bot, exc) -> bool:
    return (getattr(bot, "skip_pre_mutation_failures", False) is True
            and isinstance(exc, PaperCycleRejected) and exc.code in SKIPPABLE_BEFORE_MUTATION
            and not getattr(bot, "paper_lifecycle_halted", False) and not getattr(bot, "audit_failed", False))


def skip_paper_cycle(bot, event_id, exc):
    """Audit a live cycle that failed before any paper mutation, without latching.

    A prior latch or an unfinished cycle still halts, and so does any failure to
    audit the skip durably.
    """
    payload = {"event_id": event_id, "reject_code": exc.code, "reason": exc.reason,
               "fatal": False, "skipped": True, "execution_attempted": False}
    try:
        runtime = bot.database.get_operational_state()
        if runtime.get("paper_lifecycle_halted") or runtime.get("paper_cycle_in_progress"):
            raise PaperCycleRejected("PAPER_LIFECYCLE_HALTED", "previous uncertain lifecycle requires reconciliation")
        bot._audit("PAPER_CYCLE_SKIPPED", Severity.WARNING, payload)
        if getattr(bot, "audit_failed", False):
            raise PaperCycleAuditError("cycle skip audit was not confirmed")
        trades = tuple(economic_trade(trade) for trade in bot.manager.load_all_trades())
        paused = bot.database.get_shadow_paused()
    except Exception as failure:
        return halt_paper_cycle(bot, event_id, failure)
    return PaperCycleResult(event_id, (), (payload,), None, trades, 0, 0, paused, False, True)


def halt_paper_cycle(bot, event_id, exc, *, decisions=(), rejections=(), opened=0, closed=0):
    bot.paper_lifecycle_halted = True
    audit_complete = not (isinstance(exc, (OSError, sqlite3.Error, PaperCycleAuditError, PaperAuditError)) or getattr(bot, "audit_failed", False))
    try:
        runtime = bot.database.get_operational_state()
        if runtime.get("paper_audit_complete") is False or (getattr(exc, "code", None) == "PAPER_LIFECYCLE_HALTED" and runtime.get("paper_cycle_in_progress")):
            audit_complete = False
    except Exception:
        audit_complete = False
    bot.audit_failed = not audit_complete
    code = getattr(exc, "code", None) or getattr(exc, "detail", {}).get("reject_code") or "STATEFUL_EVENT_ERROR"
    payload = {"event_id": event_id, "reject_code": code, "error_type": type(exc).__name__, "fatal": True}
    try:
        # Incomplete is durable BEFORE attempting the final audit. A crash
        # between these writes must never manufacture a complete audit.
        bot.database.update_operational_state({"paper_lifecycle_halted": True, "halt_reason": code,
            "latest_exit_reason": "PAPER_LIFECYCLE_HALTED", "paper_audit_complete": False})
        bot.database.set_shadow_paused(True, reason=code, paused_by="paper_lifecycle")
        bot._audit("PAPER_CYCLE_HALTED", Severity.ERROR, payload, notify=True)
        if audit_complete:
            bot.database.update_operational_state({"paper_audit_complete": True})
    except Exception:
        audit_complete = False
        bot.audit_failed = True
    revoked = []
    for decision in decisions:
        if decision.accepted:
            risk = decision.risk_decision
            if risk is not None:
                risk = replace(risk, accepted=False, approved_lot=0., risk_amount_account_currency=0.,
                    reject_code="REPLAY_EVENT_ABORTED", reject_reason="paper cycle did not complete")
            decision = replace(decision, accepted=False, reject_code="REPLAY_EVENT_ABORTED",
                reject_reason="paper cycle did not complete", risk_decision=risk)
        revoked.append(decision)
    try:
        trades = tuple(economic_trade(trade) for trade in bot.manager.load_all_trades())
    except Exception:
        trades = ()
        audit_complete = False
        bot.audit_failed = True
    return PaperCycleResult(event_id, tuple(revoked), tuple(rejections)+(payload,), None,
        trades, opened, closed, True, True, audit_complete)
