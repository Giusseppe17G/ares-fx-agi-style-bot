"""Forward shadow observation loop."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime
from hashlib import sha256
from time import perf_counter, sleep
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.core.clock import Clock, resolve_clock
from agi_style_forex_bot_mt5.core.decision import DecisionContext, PipelineDecision, SharedDecisionPipeline, build_trade_signal
from agi_style_forex_bot_mt5.calibration.decision_policy import resolve_signal_profile
from agi_style_forex_bot_mt5.contracts import AccountState, Environment, Event, Severity, SignalAction
from agi_style_forex_bot_mt5.calibration import effective_profile_config
from agi_style_forex_bot_mt5.execution import MT5Connector
from agi_style_forex_bot_mt5.mt5_data_bot import MT5DataOnlyBot
from agi_style_forex_bot_mt5.ml import MLFilter
from agi_style_forex_bot_mt5.ml.prediction_audit import audit_ml_prediction
from agi_style_forex_bot_mt5.observability import AlertRuleEngine, DailySummary, HeartbeatWriter, MetricsCollector
from agi_style_forex_bot_mt5.paper_risk_calibration import evaluate_paper_trade_limits
from agi_style_forex_bot_mt5.paper_risk_calibration.paper_trade_limit_policy import PaperRiskLimits
from agi_style_forex_bot_mt5.paper_daily_risk_state import validate_micro_daily_risk
from agi_style_forex_bot_mt5.paper_risk_review import validate_micro_resume_clearance
from agi_style_forex_bot_mt5.portfolio import DynamicRiskAllocator, PortfolioGuard, SignalRanker
from agi_style_forex_bot_mt5.persistence import RecoveryManager
from agi_style_forex_bot_mt5.rejection_labeling import classify_rejection_event_type
from agi_style_forex_bot_mt5.risk import RiskEngine
from agi_style_forex_bot_mt5.strategy import evaluate_ensemble
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase, TelegramNotifier
from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter

from .lifecycle import (PaperAccountObservation, PaperCandidate, PaperCycleInput, PaperCycleRejected,
    PaperEvidence, PaperCycleAuditError, process_paper_cycle, halt_paper_cycle, skip_paper_cycle,
    skippable_before_mutation, validate_evidence, validate_account)
from .paper_fill_model import PaperFillModel
from .paper_pnl_engine import extract_paper_risk_multiplier
from .paper_position_manager import PaperPositionManager
from .paper_report import write_forward_shadow_report


MAX_SKIP_BACKOFF_SECONDS = 300


class _StartupSkipped(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _AlreadyHalted(Exception):
    """The startup skip could not be audited and already latched the lifecycle."""


@dataclass(frozen=True)
class ForwardShadowSummary:
    mode: str
    mt5_connected: bool
    cycles_completed: int
    open_trades: int | None
    paper_trades_opened: int
    paper_trades_closed: int
    heartbeat_written: bool = False
    alerts_emitted: int = 0
    telegram_commands_processed: int = 0
    shadow_paused: bool = False
    execution_attempted: bool = False
    signal_profile_used: str = ""
    stable_gate_confirmed: bool = False
    order_send_called: bool = False
    order_check_called: bool = False
    exit_reason: str = ""
    halt_reason: str = ""
    paper_shadow_paused: bool = False
    critical_alerts_recent: tuple[str, ...] = ()
    next_recommended_command: str = ""
    audit_complete: bool = True
    lifecycle_halted: bool = False
    paper_state_available: bool = True
    cycles_skipped: int = 0
    skip_reason: str = ""


class ForwardShadowBot:
    """Read MT5 data, manage paper trades, never execute broker orders."""

    def __init__(
        self,
        *,
        config: BotConfig | None = None,
        symbols: Iterable[str],
        audit_logger: JsonlAuditLogger,
        database: TelemetryDatabase,
        telegram_notifier: TelegramNotifier | None = None,
        mt5_client: Any | None = None,
        cycle_seconds: int = 30,
        max_cycles: int | None = None,
        report_dir: str = "data/reports/forward_shadow",
        stable_gate_confirmed: bool = False,
        stable_gate_decision: str = "",
        clock: Clock | None = None,
        decision_evidence_provider: Callable[..., Mapping[str, Any]] | None = None,
        ml_filter: Any | None = None,
        skip_pre_mutation_failures: bool = True,
    ) -> None:
        self.config = config or BotConfig()
        self.config.validate_safety()
        self.symbols = tuple(symbol.upper() for symbol in symbols)
        self.audit_logger = audit_logger
        self.database = database
        self.telegram_notifier = telegram_notifier
        self.mt5_client = mt5_client
        self.cycle_seconds = max(0, cycle_seconds)
        self.max_cycles = max_cycles
        self.report_dir = report_dir
        self.stable_gate_confirmed = bool(stable_gate_confirmed)
        self.stable_gate_decision = stable_gate_decision
        self.clock = resolve_clock(clock)
        self.decision_evidence_provider = decision_evidence_provider
        self.run_id = f"forward_{uuid4().hex}"
        self.connector: MT5Connector | None = None
        self.paper_cycle_results = []
        self.paper_lifecycle_halted = False
        self.audit_failed = False
        # Live runs skip closed markets and terminal outages without latching
        # (lifecycle.SKIPPABLE_BEFORE_MUTATION); explicit replay passes False.
        self.skip_pre_mutation_failures = skip_pre_mutation_failures is True
        self.manager = PaperPositionManager(database=database, fill_model=PaperFillModel(max_spread_points=self.config.max_spread_points_default, clock=self.clock, max_tick_age_seconds=self.config.max_market_snapshot_age_seconds), profile_config=self.config.profile_config or None)
        self.heartbeat = HeartbeatWriter(database)
        self.alerts = AlertRuleEngine(database)
        self.metrics = MetricsCollector(database, clock=self.clock)
        self.command_center = TelegramCommandCenter(
            database=database,
            audit_logger=audit_logger,
            daily_report_dir=f"{self.report_dir}/daily",
            run_id=self.run_id,
        )
        self.ml_filter = ml_filter if ml_filter is not None else MLFilter.load_latest_model()
        self.signal_ranker = SignalRanker()
        self.portfolio_guard = PortfolioGuard()
        self.dynamic_risk_allocator = DynamicRiskAllocator()
        self.recovery_manager = RecoveryManager(database=database, audit_logger=audit_logger, run_id=self.run_id)

    def run(self) -> ForwardShadowSummary:
        opened = closed = cycles = alerts_emitted = commands_processed = 0
        attempts = skipped = consecutive_skips = 0
        skip_reason = ""
        heartbeat_written = connected = False
        event_id = "startup"
        try:
            self._audit("FORWARD_SHADOW_STARTED", Severity.INFO, {"execution_attempted": False}, notify=True)
            recovery = self.recovery_manager.recover()
            if recovery.get("status") != "OK":
                raise PaperCycleRejected("RECOVERY_FAILED", "startup recovery failed")
            if not self._connect():
                failure = PaperCycleRejected("MT5_CONNECT_FAILED", getattr(self, "_connect_error", "") or "read-only connection failed")
                if not skippable_before_mutation(self, failure):
                    raise failure
                result = skip_paper_cycle(self, event_id, failure)
                self.paper_cycle_results.append(result)
                if result.halted:
                    raise _AlreadyHalted()
                raise _StartupSkipped(failure.code)
            if self.config.signal_profile == "BALANCED_STABLE_MICRO":
                multiplier = extract_paper_risk_multiplier(self.config.profile_config or None)
                if multiplier is None:
                    raise PaperCycleRejected("PAPER_PNL_SCALING_CONFIG_MISSING", "micro sizing multiplier is unavailable")
                self._audit("PAPER_PNL_SCALING_ACTIVE", Severity.INFO, {"paper_risk_multiplier": multiplier,
                    "pnl_formula_version": "paper_pnl_approved_lot_v1", "execution_attempted": False}, notify=True)
            while self.max_cycles is None or attempts < self.max_cycles:
                attempts += 1
                event_id = f"cycle-{attempts}"
                commands_processed += self.command_center.poll_and_process() if self.telegram_notifier is not None else 0
                observation = self._observe_account()
                connected = observation.connected is True
                try:
                    validate_account(observation, self.clock.now_utc(), self.config)
                    cycle = self._acquire_paper_cycle(observation, event_id=event_id)
                except PaperCycleRejected as exc:
                    if not skippable_before_mutation(self, exc):
                        raise
                    result = skip_paper_cycle(self, event_id, exc)
                    self.paper_cycle_results.append(result)
                else:
                    result = self.process_paper_cycle(cycle)
                opened += result.opened
                closed += result.closed
                if result.halted:
                    break
                if result.valuation is None:
                    # Skipped before any paper mutation: keep the heartbeat
                    # alive, report why, and back off before retrying.
                    skipped += 1
                    consecutive_skips += 1
                    skip_reason = str(result.rejections[-1].get("reject_code", ""))
                    self.heartbeat.write({"mode": "forward-shadow", "mt5_connected": connected,
                        "symbols_seen": len(self.symbols), "symbols_rejected": 0,
                        "open_paper_trades": len(self.manager.load_open_trades()), "closed_paper_trades_today": closed,
                        "last_error": skip_reason, "shadow_paused": result.paused,
                        "signal_profile_used": self.config.signal_profile, "stable_gate_confirmed": self.stable_gate_confirmed,
                        "stable_gate_decision": self.stable_gate_decision, "execution_attempted": False})
                    heartbeat_written = True
                    if self.max_cycles is None and self.cycle_seconds:
                        sleep(min(self.cycle_seconds * 2 ** min(consecutive_skips - 1, 4), MAX_SKIP_BACKOFF_SECONDS))
                    continue
                consecutive_skips = 0
                cycles += 1
                heartbeat = self.heartbeat.write({"mode": "forward-shadow", "mt5_connected": connected,
                    "symbols_seen": len(self.symbols), "symbols_rejected": len(result.rejections),
                    "open_paper_trades": result.valuation["open_positions"], "closed_paper_trades_today": closed,
                    "last_error": "", "shadow_paused": result.paused,
                    "signal_profile_used": self.config.signal_profile, "stable_gate_confirmed": self.stable_gate_confirmed,
                    "stable_gate_decision": self.stable_gate_decision, "execution_attempted": False})
                heartbeat_written = True
                # Economic pause decisions belong to the shared lifecycle;
                # these transport/operational alerts cannot change its ledger.
                metrics = {**self.metrics.collect(), "mt5_connected": connected, "sqlite_status": "OK", "jsonl_status": "OK"}
                cycle_alerts = self.alerts.evaluate(metrics)
                alerts_emitted += self.alerts.persist(cycle_alerts)
                if cycle_alerts:
                    self._audit("OPERATIONAL_ALERTS", Severity.WARNING,
                        {"event_id": event_id, "alerts": [alert.to_dict() for alert in cycle_alerts], "execution_attempted": False}, notify=True)
                self._maybe_daily_summary()
                self._audit("HEARTBEAT", Severity.INFO, {**heartbeat, "event_id": event_id})
                self._audit("FORWARD_SHADOW_CYCLE", Severity.INFO, {"event_id": event_id,
                    "cycle": cycles, "open_trades": result.valuation["open_positions"], "heartbeat_written": True,
                    "alerts_emitted": alerts_emitted, "telegram_commands_processed": commands_processed,
                    "shadow_paused": result.paused, "execution_attempted": False})
                if self.max_cycles is None and self.cycle_seconds:
                    sleep(self.cycle_seconds)
            if not self.paper_lifecycle_halted:
                write_forward_shadow_report(self.manager.load_all_trades(), self.report_dir)
                self._audit("FORWARD_SHADOW_STOPPED", Severity.INFO, {"cycles": cycles, "execution_attempted": False}, notify=True)
        except _StartupSkipped as startup:
            skipped, skip_reason = 1, startup.code
        except _AlreadyHalted:
            pass
        except Exception as exc:
            result = halt_paper_cycle(self, event_id, exc)
            self.paper_cycle_results.append(result)
        try:
            count = len(self.manager.load_open_trades())
        except Exception:
            count = None
            self.audit_failed = True
        initial_failure = ""
        if cycles == 0 and self.paper_cycle_results:
            reason = self.paper_cycle_results[-1].rejections[-1].get("reject_code") if self.paper_cycle_results[-1].rejections else ""
            if reason in {"RECOVERY_FAILED", "MT5_CONNECT_FAILED", "ACCOUNT_INFO_UNAVAILABLE", "ACCOUNT_INFO_INVALID",
                          "ACCOUNT_REAL_DETECTED_READ_ONLY", "MT5_CONNECTION_UNVERIFIED"}:
                initial_failure = "CONFIG_ERROR"
        if not initial_failure and skip_reason and not self.paper_lifecycle_halted and consecutive_skips:
            initial_failure = "PAPER_CYCLE_SKIPPED"
        return self._summary(connected, cycles, count, opened, closed,
            heartbeat_written, alerts_emitted, commands_processed, exit_reason=initial_failure,
            cycles_skipped=skipped, skip_reason=skip_reason)

    def process_paper_cycle(self, cycle: PaperCycleInput):
        """Public economic lifecycle also used by explicit quote replay."""
        return process_paper_cycle(self, cycle)

    def _observe_account(self) -> PaperAccountObservation:
        assert self.connector is not None
        account = self._read_account()
        observed_at = self.clock.now_utc()
        terminal_info = getattr(self.connector.mt5, "terminal_info", None)
        terminal = terminal_info() if callable(terminal_info) else None
        connected = getattr(terminal, "connected", None)
        return PaperAccountObservation(account, observed_at, connected)

    def _summary(
        self,
        mt5_connected: bool,
        cycles_completed: int,
        open_trades: int,
        paper_trades_opened: int,
        paper_trades_closed: int,
        heartbeat_written: bool,
        alerts_emitted: int,
        telegram_commands_processed: int,
        exit_reason: str = "",
        halt_reason: str = "",
        cycles_skipped: int = 0,
        skip_reason: str = "",
    ) -> ForwardShadowSummary:
        try:
            state = self.database.get_operational_state()
            alerts = self.database.fetch_all("alerts")
            paused = self.database.get_shadow_paused()
        except Exception:
            state, alerts, paused = {"halt_reason": "PAPER_STORAGE_UNAVAILABLE"}, [], True
            open_trades = None
            self.audit_failed = self.paper_lifecycle_halted = True
        critical_payloads = [_safe_json(row["payload_json"]) for row in alerts[-5:]]
        critical = tuple(str(payload.get("alert_code", "")) for payload in critical_payloads if str(payload.get("severity", "")).upper() == "CRITICAL")
        computed_halt = halt_reason or str(state.get("halt_reason") or state.get("paused_reason") or "")
        computed_exit = exit_reason or str(state.get("latest_exit_reason") or ("SHADOW_MANUALLY_PAUSED" if paused else ""))
        return ForwardShadowSummary(
            mode="forward-shadow",
            mt5_connected=mt5_connected,
            cycles_completed=cycles_completed,
            open_trades=open_trades,
            paper_trades_opened=paper_trades_opened,
            paper_trades_closed=paper_trades_closed,
            heartbeat_written=heartbeat_written,
            alerts_emitted=alerts_emitted,
            telegram_commands_processed=telegram_commands_processed,
            shadow_paused=paused,
            execution_attempted=False,
            signal_profile_used=self.config.signal_profile,
            stable_gate_confirmed=self.stable_gate_confirmed,
            order_send_called=False,
            order_check_called=False,
            exit_reason=computed_exit,
            halt_reason=computed_halt,
            paper_shadow_paused=paused,
            critical_alerts_recent=critical,
            next_recommended_command=_next_recommended_command(computed_halt or computed_exit),
            audit_complete=not self.audit_failed, lifecycle_halted=self.paper_lifecycle_halted,
            paper_state_available=open_trades is not None,
            cycles_skipped=cycles_skipped, skip_reason=skip_reason,
        )

    def _connect(self) -> bool:
        try:
            self.connector = MT5Connector(config=self.config, mt5_client=self.mt5_client)
        except RuntimeError as exc:
            # MetaTrader5 package missing: nothing was read or written yet.
            self._connect_error = str(exc)
            return False
        initialize = getattr(self.connector.mt5, "initialize", None)
        return (not callable(initialize)) or initialize() is True

    def _read_account(self) -> AccountState | None:
        assert self.connector is not None
        account_info = getattr(self.connector.mt5, "account_info", None)
        if not callable(account_info):
            return None
        raw = account_info()
        if raw is None:
            return None
        trade_mode_raw = getattr(raw, "trade_mode", None)
        is_demo = not isinstance(trade_mode_raw, bool) and self.connector._is_demo_trade_mode(trade_mode_raw)
        return AccountState(
            login=getattr(raw, "login", None),
            trade_mode="DEMO" if is_demo else str(trade_mode_raw or "UNKNOWN"),
            balance=_account_number(getattr(raw, "balance", None)),
            equity=_account_number(getattr(raw, "equity", None)),
            margin_free=_account_number(getattr(raw, "margin_free", None)),
            currency=getattr(raw, "currency", None),
            is_demo=is_demo,
            trade_allowed=getattr(raw, "trade_allowed", None) is True,
        )

    def _scan_new_paper_trades(self, account: AccountState) -> int:
        """Compatibility entry point; acquisition and lifecycle stay shared."""
        assert self.connector is not None
        terminal_info = getattr(self.connector.mt5, "terminal_info", None)
        terminal = terminal_info() if callable(terminal_info) else None
        observation = PaperAccountObservation(account, self.clock.now_utc(), getattr(terminal, "connected", None))
        cycle = self._acquire_paper_cycle(observation, event_id=f"scan-{len(self.paper_cycle_results)+1}")
        return self.process_paper_cycle(cycle).opened

    def _acquire_paper_cycle(self, observation: PaperAccountObservation, *, event_id: str) -> PaperCycleInput:
        assert self.connector is not None
        # The data reader handles expected market-data rejection internally.
        # Its audit sink must nevertheless latch a storage failure even when
        # that reader catches the underlying exception before returning None.
        helper = MT5DataOnlyBot(config=self.config, symbols=self.symbols, audit_logger=_RequiredAuditSink(self, self.audit_logger),
            database=_RequiredAuditSink(self, self.database), telegram_notifier=self.telegram_notifier,
            mt5_client=self.connector.mt5, run_id=self.run_id)
        helper.connector = self.connector
        quotes, candidates, tick_ms = {}, [], {}
        # Measured evidence is rebuilt from this cycle's reads only.
        begin_evidence = getattr(self.decision_evidence_provider, "begin_cycle", None)
        observe_evidence = getattr(self.decision_evidence_provider, "observe_symbol", None)
        if callable(begin_evidence):
            begin_evidence(account_trade_allowed=getattr(observation.account, "trade_allowed", None))
        # Collect every mark before position management. No partial book update
        # or secondary quote lookup is permitted by the economic processor.
        for trade in self.manager.load_open_trades():
            started = perf_counter()
            quote = self._snapshot_for(trade.broker_symbol, trade.symbol)
            if quote is not None:
                quotes[trade.symbol] = quote
                tick_ms[trade.symbol] = _elapsed_ms(started)
        for symbol in self.symbols:
            check, resolution = self.connector.resolve_symbol(symbol)
            if not check.accepted or resolution is None:
                self._audit("SYMBOL_REJECTED", Severity.WARNING, check.payload, symbol=symbol)
                continue
            snapshot = quotes.get(symbol)
            if snapshot is None:
                started = perf_counter()
                snapshot = self._snapshot_for(resolution.broker_symbol, resolution.canonical_symbol)
                tick_ms[symbol] = _elapsed_ms(started)
            if snapshot is None:
                continue
            snapshot = replace(snapshot, timeframe="M5")
            quotes[symbol] = snapshot
            started = perf_counter()
            bars_by_tf = helper._read_timeframes(resolution.canonical_symbol, resolution.broker_symbol, snapshot)
            rates_ms = _elapsed_ms(started)
            if self.audit_failed:
                raise PaperCycleAuditError("market-data audit was not durably confirmed")
            if bars_by_tf is None:
                continue
            if callable(observe_evidence):
                observe_evidence(symbol, bars_by_tf, tick_latency_ms=tick_ms[symbol], rates_latency_ms=rates_ms)
            try:
                features = helper._features_from_bars(bars_by_tf["M5"], snapshot)
            except Exception as exc:
                self._audit("FORWARD_FEATURE_BUILD_FAILED", Severity.WARNING,
                    self._feature_build_error_payload(symbol, exc, bars_by_tf.get("M5")), symbol=symbol)
                continue
            candidates.append(PaperCandidate(symbol, "M5", resolution.broker_symbol, bars_by_tf["M5"], features))
        return PaperCycleInput(event_id, observation.observed_at_utc, observation, quotes, tuple(candidates), {})

    def _paper_signal_already_traded(self, decision_id: str, symbol: str) -> bool:
        """One persisted entry per symbol/closed-bar/profile identity.

        Rejected decisions are retryable; a created paper trade, including a
        subsequently closed trade, consumes the identity. Store failures raise
        before evaluation. Direct manager retries retain strict intent checks.
        """
        if not isinstance(decision_id, str) or not decision_id or not isinstance(symbol, str) or not symbol:
            raise ValueError("paper candidate identity is required")
        matches = [trade for trade in self.manager.load_all_trades() if trade.signal_id == decision_id]
        if not matches:
            return False
        if len(matches) != 1 or matches[0].symbol != symbol or matches[0].status not in {"OPEN", "CLOSED"}:
            raise ValueError("paper candidate identity conflicts with stored history")
        self._audit("CANDIDATE_ALREADY_TRADED", Severity.INFO,
            {"signal_id": decision_id, "symbol": symbol, "existing_status": matches[0].status,
             "reason": "a paper trade already consumed this closed-bar/profile identity",
             "execution_attempted": False}, symbol=symbol)
        return True

    def _refresh_paper_risk_state(self, account, *, snapshots=None):
        """Mark every open paper position and persist the daily risk observation."""
        from .decision_state import build_paper_decision_state

        trades = self.manager.load_all_trades()
        open_trades = [trade for trade in trades if trade.status == "OPEN"]
        supplied = snapshots is not None
        snapshots = dict(snapshots or {})
        for trade in open_trades:
            if trade.symbol not in snapshots:
                if supplied:
                    raise PaperCycleRejected("OPEN_POSITION_QUOTE_MISSING", "supplied cycle has no quote for open position")
                observed = self._snapshot_for(trade.broker_symbol, trade.symbol)
                if observed is None:
                    raise ValueError("open paper position snapshot is unavailable")
                snapshots[trade.symbol] = observed
        now = self.clock.now_utc()
        return build_paper_decision_state(
            database=self.database, trades=trades, snapshots_by_symbol=snapshots,
            account_template=account, now_utc=now,
            max_snapshot_age_seconds=self.config.max_market_snapshot_age_seconds,
            max_daily_drawdown_pct=self.config.max_daily_drawdown_pct,
        )

    def _paper_decision_context(self, snapshot, features, account, broker_symbol, *, snapshots=None, evidence=None) -> DecisionContext:
        """Acquire a complete paper book; missing evidence remains a blocker."""
        paper_state = self._refresh_paper_risk_state(account, snapshots={**dict(snapshots or {}), snapshot.symbol: snapshot})
        now = paper_state.risk_state.now_utc
        payloads = paper_state.portfolio_open_trades
        if evidence is None and self.decision_evidence_provider is not None:
            evidence = self.decision_evidence_provider(snapshot, features, payloads)
        evidence = validate_evidence(evidence, self.clock.now_utc(), self.config, has_exposure=bool(payloads))
        available = _decision_datetime(features.get("available_at_utc"))
        if available is None:
            raise ValueError("closed-bar feature availability evidence is missing")
        profile = resolve_signal_profile(self.config)
        identity = "|".join((snapshot.symbol, snapshot.timeframe, available.isoformat(), profile["profile_hash"]))
        bundle = getattr(self.ml_filter, "bundle", None)
        model_metadata = dict(bundle.get("metadata") or {}) if isinstance(bundle, Mapping) else {}
        model_available = _decision_datetime(model_metadata.get("created_at_utc"))
        return DecisionContext(
            decision_id="paper_" + sha256(identity.encode("utf-8")).hexdigest(),
            config=self.config, snapshot=snapshot, features=dict(features),
            features_available_at_utc=available, state_available_at_utc=now,
            account=paper_state.account, risk_state=paper_state.risk_state,
            open_trades=payloads, broker_symbol=broker_symbol,
            broker_readiness_score=evidence.broker_readiness_score,
            correlation=evidence.correlation, shadow_paused=self.database.get_shadow_paused(),
            consecutive_losses=paper_state.risk_state.consecutive_losses,
            allow_disabled_ml=self.config.paper_allow_disabled_ml,
            ml_model_available_at_utc=model_available,
        )

    def _evaluate_paper_decision(self, context: DecisionContext) -> PipelineDecision:
        """The real forward caller; durable result audit precedes every paper fill."""
        def persist_signal(signal, ctx):
            self._audit("SIGNAL_GENERATED", Severity.INFO, {
                "signal_id": signal.signal_id, "symbol": signal.symbol,
                "created_at_utc": signal.created_at_utc.isoformat(),
                "direction": signal.direction.value, "sl_price": signal.sl_price,
                "tp_price": signal.tp_price, "risk_pct": signal.risk_pct,
                "strategy_name": signal.strategy_name, "metadata": dict(signal.metadata),
                "execution_attempted": False,
            }, symbol=signal.symbol)
            return True

        pipeline = SharedDecisionPipeline(
            clock=self.clock, strategy_evaluator=evaluate_ensemble, signal_builder=build_trade_signal,
            risk_engine=RiskEngine(self.config), ml_filter=self.ml_filter,
            signal_ranker=self.signal_ranker, portfolio_guard=self.portfolio_guard,
            dynamic_risk_allocator=self.dynamic_risk_allocator, persist_signal=persist_signal,
            paper_limit_evaluator=lambda ctx, now: self._paper_risk_guard(now=now),
        )
        decision = pipeline.evaluate(context)
        self._audit("PAPER_DECISION_COMPLETED", Severity.INFO if decision.accepted else Severity.WARNING,
                    decision.to_dict(), symbol=context.snapshot.symbol)
        for stage in decision.trace:
            if stage.status == "skipped":
                continue
            event_type = {"strategy": "SIGNAL_DETECTED", "risk_engine": "RISK_DECISION",
                "ml_filter": "ML_PREDICTION", "signal_ranker": "SIGNAL_RANKED",
                "portfolio_guard": "PORTFOLIO_DECISION", "dynamic_risk": "DYNAMIC_RISK_ADJUSTED",
                "paper_limits": "PAPER_RISK_DECISION"}.get(stage.stage_id)
            if event_type:
                payload = {**stage.payload, "signal_id": context.decision_id,
                           "symbol": context.snapshot.symbol, "stage_status": stage.status,
                           "timestamp_utc": decision.timestamp_utc.isoformat() if decision.timestamp_utc else "",
                           "execution_attempted": False}
                if event_type == "ML_PREDICTION" and payload.get("ml_status"):
                    try:
                        audit_ml_prediction(self.database, payload)
                    except Exception:
                        self.audit_failed = True
                        raise
                self._audit(event_type, Severity.INFO if stage.status == "passed" else Severity.WARNING,
                            payload, symbol=context.snapshot.symbol)
        return decision

    def _feature_build_error_payload(self, symbol: str, exc: Exception, frame: Any) -> dict[str, Any]:
        message = str(exc)
        code = message.split(":", 1)[0].strip().upper() if message else "FEATURE_ENGINE_EXCEPTION"
        if not code.startswith("LIVE_") and not code.startswith("FEATURE_"):
            code = "FEATURE_ENGINE_EXCEPTION"
        columns = tuple(getattr(frame, "columns", ()))
        rows = int(len(frame)) if frame is not None and hasattr(frame, "__len__") else 0
        timestamp_status = "UNKNOWN"
        first_timestamp = ""
        last_timestamp = ""
        if frame is not None and "timestamp_utc" in columns:
            try:
                timestamp_status = "OK" if getattr(frame["timestamp_utc"], "dt", None) is not None else "LIVE_TIMESTAMP_NOT_DATETIME"
                first_timestamp = frame["timestamp_utc"].iloc[0].isoformat() if rows else ""
                last_timestamp = frame["timestamp_utc"].iloc[-1].isoformat() if rows else ""
            except Exception:
                timestamp_status = "LIVE_TIMESTAMP_NOT_DATETIME"
        return {
            "symbol": symbol,
            "feature_build_error_type": code,
            "feature_build_exception": message,
            "missing_columns": [column for column in ("timestamp_utc", "open", "high", "low", "close", "tick_volume", "spread", "real_volume") if column not in columns],
            "invalid_dtypes": [],
            "row_count_by_timeframe": {"M5": rows},
            "timestamp_status": timestamp_status,
            "null_counts": {},
            "first_timestamp_utc": first_timestamp,
            "last_timestamp_utc": last_timestamp,
            "schema_after": list(columns),
            "blockers": [code],
            "execution_attempted": False,
        }

    def _decorate_stable_trade(self, trade: PaperTrade, strategy_signal: Any, features: Mapping[str, Any]) -> PaperTrade:
        if self.config.signal_profile not in {"BALANCED_STABLE", "BALANCED_STABLE_MICRO", "BALANCED_STABLE_MICRO_V2"}:
            return trade
        effective = effective_profile_config(self.config.signal_profile, source="forward-shadow", profile_config=self.config.profile_config or None)
        metadata = {
            **dict(trade.metadata),
            "profile": self.config.signal_profile,
            "signal_profile_used": self.config.signal_profile,
            "stable_profile_hash": effective.profile_hash,
            "stable_filters_applied": bool(effective.filters.get("apply_stability_filters", False)),
            "risk_profile_used": getattr(self.config, "risk_profile_used", "") or self.config.signal_profile,
            "entry_paper_risk_multiplier": self.config.paper_risk_multiplier,
            "stable_gate_decision": self.stable_gate_decision,
            "stable_gate_confirmed": self.stable_gate_confirmed,
            "setup_score": strategy_signal.metadata.get("setup_score", strategy_signal.score),
            "ensemble_score": strategy_signal.score,
            "component_scores": dict(strategy_signal.metadata.get("component_scores", {})),
            "session": str(features.get("session", "")),
            "regime": str(features.get("regime", "")),
        }
        if metadata.get("pnl_basis") == "APPROVED_LOT_UNSCALED_V1":
            metadata.pop("paper_risk_multiplier", None)
        else:
            metadata["paper_risk_multiplier"] = self.config.paper_risk_multiplier
        updated = trade.replace(metadata=metadata)
        self.database.update_paper_trade(updated.to_dict())
        self.database.insert_paper_trade_event(updated.paper_trade_id, "STABLE_PROFILE_METADATA_ATTACHED", updated.to_dict())
        return updated

    def _paper_risk_guard(self, *, now: datetime | None = None) -> dict[str, Any]:
        if self._manage_open_trades_only_enabled():
            return {
                "paper_risk_status": "PAPER_DAILY_RISK_RESUME_MANAGE_OPEN_TRADES_ONLY",
                "paper_risk_profile": self.config.signal_profile,
                "can_open_new_paper_trade": False,
                "blocking_reason": "MANAGE_OPEN_TRADES_ONLY",
                "paper_resume_mode": "MANAGE_OPEN_TRADES_ONLY",
                "new_entries_blocked": True,
                "paper_exit_evaluation_allowed": True,
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        limits = PaperRiskLimits(
            profile=self.config.signal_profile, paper_risk_multiplier=self.config.paper_risk_multiplier,
            max_open_paper_trades=self.config.max_open_paper_trades,
            max_paper_trades_per_day=self.config.max_paper_trades_per_day,
            cooldown_after_loss_minutes=self.config.cooldown_after_loss_minutes,
            cooldown_after_drawdown_halt_minutes=self.config.cooldown_after_drawdown_halt_minutes,
            block_new_entries_after_daily_halt=self.config.block_new_entries_after_daily_halt,
            manual_resume_required=self.config.manual_resume_required,
        )
        status = evaluate_paper_trade_limits(database=self.database, limits=limits, now=now or self.clock.now_utc())
        if self.config.signal_profile == "BALANCED_STABLE_MICRO" and status.get("blocking_reason") == "PAPER_DRAWDOWN_HALT_BLOCK" and getattr(self.config, "paper_risk_clearance", ""):
            clearance = validate_micro_resume_clearance(
                database=self.database,
                clearance_ledger=getattr(self.config, "paper_risk_clearance", ""),
                profile=self.config.signal_profile,
                profile_config=self.config.profile_config or None,
                daily_risk_ledger=getattr(self.config, "paper_daily_risk_ledger", ""),
            )
            daily = validate_micro_daily_risk(
                database=self.database,
                clearance_ledger=getattr(self.config, "paper_risk_clearance", ""),
                daily_risk_ledger=getattr(self.config, "paper_daily_risk_ledger", ""),
                profile_config=self.config.profile_config or None,
            )
            if clearance.get("accepted") and daily.get("accepted"):
                status.update(
                    {
                        "paper_risk_status": "PAPER_RISK_CLEAR_FOR_MICRO_SHADOW",
                        "daily_drawdown_status": "CLEARED_STALE_HALT",
                        "can_open_new_paper_trade": True,
                        "blocking_reason": "",
                        "manual_review_required": False,
                        "cleared_profile": "BALANCED_STABLE_MICRO",
                        "paper_risk_clearance_status": clearance.get("paper_risk_clearance_status"),
                        "paper_risk_clearance_id": clearance.get("paper_risk_clearance_id"),
                        "paper_risk_profile": "BALANCED_STABLE_MICRO",
                        "paper_daily_risk_status": daily.get("paper_daily_risk_status"),
                        "daily_risk_ledger_status": daily.get("daily_risk_ledger_status"),
                    }
                )
            else:
                status["paper_daily_risk_status"] = daily.get("paper_daily_risk_status", "")
                status["daily_risk_ledger_status"] = daily.get("daily_risk_ledger_status", "")
        return status

    def _manage_open_trades_only_enabled(self) -> bool:
        state = self.database.get_operational_state()
        return self.config.signal_profile == "BALANCED_STABLE_MICRO_V2" and str(state.get("paper_resume_mode", "")).upper() == "MANAGE_OPEN_TRADES_ONLY"

    def _micro_legacy_drawdown_adjusted_metrics(self, metrics: Mapping[str, Any]) -> dict[str, Any]:
        adjusted = dict(metrics)
        if self.config.signal_profile != "BALANCED_STABLE_MICRO":
            return adjusted
        daily = validate_micro_daily_risk(
            database=self.database,
            clearance_ledger=getattr(self.config, "paper_risk_clearance", ""),
            daily_risk_ledger=getattr(self.config, "paper_daily_risk_ledger", ""),
            profile_config=self.config.profile_config or None,
        )
        if daily.get("accepted") and daily.get("legacy_drawdown_quarantined"):
            adjusted["legacy_drawdown_quarantined"] = True
            adjusted["legacy_quarantined_halt_count"] = daily.get("legacy_quarantined_halt_count", 0)
            adjusted["drawdown_basis"] = "SCALED_PAPER_PNL_ONLY"
            adjusted["drawdown_paper"] = 0.0
            self._audit(
                "PAPER_LEGACY_DRAWDOWN_QUARANTINED",
                Severity.INFO,
                {
                    "legacy_quarantined_halt_count": daily.get("legacy_quarantined_halt_count", 0),
                    "drawdown_basis": "SCALED_PAPER_PNL_ONLY",
                    "execution_attempted": False,
                },
                notify=False,
            )
        return adjusted

    def _stale_shadow_pause_cleared(self) -> bool:
        if self.config.signal_profile != "BALANCED_STABLE_MICRO":
            return False
        if not getattr(self.config, "paper_daily_risk_ledger", ""):
            return False
        daily = validate_micro_daily_risk(
            database=self.database,
            clearance_ledger=getattr(self.config, "paper_risk_clearance", ""),
            daily_risk_ledger=getattr(self.config, "paper_daily_risk_ledger", ""),
            profile_config=self.config.profile_config or None,
        )
        return bool(daily.get("accepted"))

    def _forward_candidate_payload(self, symbol: str, strategy_signal: Any, features: Mapping[str, Any]) -> dict[str, Any]:
        effective = effective_profile_config(self.config.signal_profile, source="forward-shadow", profile_config=self.config.profile_config or None)
        metadata = dict(strategy_signal.metadata)
        blockers = tuple(metadata.get("blocking_reasons") or strategy_signal.reasons or ("NO_SETUP_DETECTED",))
        threshold_failures = self._forward_threshold_failures(strategy_signal.score, metadata, effective.thresholds)
        near_distance = max(0.0, float(effective.thresholds.get("ensemble_min_score", 0.0)) - float(strategy_signal.score or 0.0))
        near_miss = strategy_signal.action == SignalAction.NONE and near_distance <= float(effective.thresholds.get("near_miss_window", 8.0))
        return {
            "symbol": symbol,
            "strategy_name": strategy_signal.strategy_name,
            "action": strategy_signal.action.value,
            "signal_score": strategy_signal.score,
            "setup_score": metadata.get("setup_quality_score", metadata.get("setup_score", 0.0)),
            "ensemble_score": strategy_signal.score,
            "component_scores": dict(metadata.get("component_scores") or {}),
            "thresholds_used": effective.thresholds,
            "profile_hash": effective.profile_hash,
            "passed_thresholds": not threshold_failures,
            "threshold_failures": threshold_failures,
            "blocking_reasons": blockers,
            "child_signals": metadata.get("child_signals", ()),
            "near_miss": near_miss,
            "near_miss_distance": near_distance,
            "top_blocking_reason": str(blockers[0]) if blockers else "NO_SETUP_DETECTED",
            "session": str(features.get("session", "")),
            "regime": str(features.get("regime", "")),
            "execution_attempted": False,
        }

    def _forward_threshold_failures(self, score: float, metadata: Mapping[str, Any], thresholds: Mapping[str, Any]) -> tuple[str, ...]:
        failures: list[str] = []
        if float(score or 0.0) < float(thresholds.get("ensemble_min_score", 0.0) or 0.0):
            failures.append("ENSEMBLE_SCORE_LOW")
        components = dict(metadata.get("component_scores") or {})
        if components:
            if min(float(value) for value in components.values()) < float(thresholds.get("min_component_score", 0.0) or 0.0):
                failures.append("COMPONENT_SCORE_LOW")
            for key, code in (("cost_fit", "COST_BLOCK"), ("structure_fit", "STRUCTURE_BLOCK"), ("volatility_fit", "VOLATILITY_BLOCK"), ("session_fit", "SESSION_BLOCK")):
                if float(components.get(key, 0.0) or 0.0) < float(thresholds.get(f"{key}_min", 0.0) or 0.0):
                    failures.append(code)
        return tuple(dict.fromkeys(failures))

    def _consecutive_paper_losses(self) -> int:
        losses = 0
        for trade in reversed(self.manager.load_all_trades()):
            if trade.status != "CLOSED":
                continue
            if trade.r_multiple < 0:
                losses += 1
                continue
            break
        return losses

    def _snapshot_for(self, broker_symbol: str, canonical_symbol: str):
        assert self.connector is not None
        check, snapshot = self.connector.ensure_symbol_snapshot(broker_symbol, canonical_symbol=canonical_symbol, now_utc=self.clock.now_utc(), source="forward-shadow")
        if not check.accepted:
            event_type = classify_rejection_event_type(reject_code=check.code, reject_reason=check.reason, payload=check.payload)
            self._audit(event_type, Severity.WARNING, check.payload, symbol=canonical_symbol)
            return None
        if check.payload.get("timestamp_normalized"):
            event_type = "STABLE_TICK_TIME_NORMALIZED" if self.config.signal_profile in {"BALANCED_STABLE", "BALANCED_STABLE_MICRO"} else "TICK_TIME_NORMALIZED"
            self._audit(
                event_type,
                Severity.INFO,
                {
                    "canonical_symbol": canonical_symbol,
                    "broker_symbol": broker_symbol,
                    "timestamp_normalized": True,
                    "broker_time_offset_seconds": check.payload.get("broker_time_offset_seconds"),
                    "tick_age_seconds_normalized": check.payload.get("tick_age_seconds_normalized"),
                    "tick_time_status": check.payload.get("tick_time_status"),
                    "execution_attempted": False,
                },
                symbol=canonical_symbol,
            )
        return snapshot

    def _audit(self, event_type: str, severity: Severity, payload: dict[str, Any], *, symbol: str | None = None, notify: bool = False) -> None:
        identity = payload.get("signal_id") or payload.get("decision_id")
        signal_id = identity if isinstance(identity, str) and identity else None
        event_identity = payload.get("event_id")
        correlation_key = signal_id or event_identity or event_type
        correlation_id = f"{self.run_id}:{correlation_key}"
        causation_id = sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest() if signal_id or event_identity else None
        event = Event.create(
            run_id=self.run_id,
            environment=Environment.DEMO,
            severity=severity,
            module="forward_shadow",
            event_type=event_type,
            message=event_type.lower(),
            correlation_id=correlation_id,
            signal_id=signal_id,
            causation_id=causation_id,
            symbol=symbol,
            payload=payload,
        )
        event = replace(event, timestamp_utc=self.clock.now_utc())
        try:
            self.audit_logger.append_event(event)
            self.database.insert_event(event)
        except Exception:
            self.audit_failed = True
            raise
        if notify and self.telegram_notifier is not None:
            try:
                self.telegram_notifier.notify_event(event)
            except Exception as exc:
                error = Event.create(
                    run_id=self.run_id,
                    environment=Environment.DEMO,
                    severity=Severity.ERROR,
                    module="telegram",
                    event_type="TELEGRAM_ERROR",
                    message=str(exc),
                    correlation_id=correlation_id,
                    signal_id=signal_id,
                    causation_id=event.event_id,
                    payload={"error": str(exc)},
                )
                self.audit_logger.append_event(error)
                self.database.insert_event(error)

    def _maybe_daily_summary(self) -> None:
        state = self.database.get_operational_state()
        today = str(self.heartbeat.database.get_latest_health().get("last_heartbeat_utc") or "")[:10]
        last = str(state.get("last_daily_summary_utc") or "")[:10]
        if today and today != last:
            DailySummary(self.database, f"{self.report_dir}/daily").generate()


def forward_summary_to_json(summary: ForwardShadowSummary) -> str:
    payload = asdict(summary) if is_dataclass(summary) else vars(summary)
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


class _RequiredAuditSink:
    """Preserve a required audit failure across legacy reader catch blocks."""

    def __init__(self, bot, target):
        self.bot, self.target = bot, target

    def __getattr__(self, name):
        method = getattr(self.target, name)
        if name not in {"append_event", "insert_event"}:
            return method
        def persist(*args, **kwargs):
            try:
                return method(*args, **kwargs)
            except Exception:
                self.bot.audit_failed = True
                raise
        return persist


def _safe_json(payload: str) -> dict[str, Any]:
    try:
        return json.loads(payload)
    except Exception:
        return {}


def _elapsed_ms(started: float) -> int:
    return int(round((perf_counter() - started) * 1000))


def _next_recommended_command(reason: str) -> str:
    if reason in {"PAPER_DAILY_DRAWDOWN_HALT", "PAPER_STATE_ERROR", "OPEN_TRADES_REVIEW_REQUIRED"}:
        return "py -m agi_style_forex_bot_mt5.cli --mode paper-state-report --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --log-dir data\\logs\\forward-shadow-stable --output-dir data\\reports\\paper_state"
    if reason == "SHADOW_MANUALLY_PAUSED":
        return "py -m agi_style_forex_bot_mt5.cli --mode resume-shadow --sqlite data\\sqlite\\forward-shadow-stable.sqlite3 --reason \"manual resume after review\""
    if reason == "ALL_SYMBOLS_REJECTED":
        return "py -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --symbols EURUSD,GBPUSD,USDJPY --sqlite data\\sqlite\\mt5-diagnose.sqlite3"
    return ""


def _paper_risk_event_type(reason: str) -> str:
    if reason in {"PAPER_MAX_OPEN_TRADES_BLOCK", "PAPER_DAILY_TRADE_LIMIT_BLOCK", "PAPER_COOLDOWN_BLOCK", "PAPER_DRAWDOWN_HALT_BLOCK"}:
        return reason
    return "PAPER_RISK_LIMIT_BLOCK"


def _decision_datetime(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _account_number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else float("nan")
