"""Forward shadow observation loop."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from time import sleep
from typing import Any, Iterable, Mapping
from uuid import uuid4

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import AccountState, Environment, Event, RiskDecision, Severity, SignalAction
from agi_style_forex_bot_mt5.calibration import effective_profile_config
from agi_style_forex_bot_mt5.execution import MT5Connector
from agi_style_forex_bot_mt5.mt5_data_bot import MT5DataOnlyBot
from agi_style_forex_bot_mt5.ml import MLFilter
from agi_style_forex_bot_mt5.ml.prediction_audit import audit_ml_prediction
from agi_style_forex_bot_mt5.observability import AlertRuleEngine, DailySummary, HeartbeatWriter, MetricsCollector
from agi_style_forex_bot_mt5.portfolio import DynamicRiskAllocator, PortfolioGuard, SignalRanker
from agi_style_forex_bot_mt5.persistence import RecoveryManager
from agi_style_forex_bot_mt5.risk import RiskRuntimeState
from agi_style_forex_bot_mt5.strategy import evaluate_ensemble
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase, TelegramNotifier
from agi_style_forex_bot_mt5.telegram_command_center import TelegramCommandCenter

from .paper_fill_model import PaperFillModel
from .paper_position_manager import PaperPositionManager
from .paper_report import write_forward_shadow_report


@dataclass(frozen=True)
class ForwardShadowSummary:
    mode: str
    mt5_connected: bool
    cycles_completed: int
    open_trades: int
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
        self.run_id = f"forward_{uuid4().hex}"
        self.connector: MT5Connector | None = None
        self.manager = PaperPositionManager(database=database, fill_model=PaperFillModel(max_spread_points=self.config.max_spread_points_default))
        self.heartbeat = HeartbeatWriter(database)
        self.alerts = AlertRuleEngine(database)
        self.metrics = MetricsCollector(database)
        self.command_center = TelegramCommandCenter(
            database=database,
            audit_logger=audit_logger,
            daily_report_dir=f"{self.report_dir}/daily",
            run_id=self.run_id,
        )
        self.ml_filter = MLFilter.load_latest_model()
        self.signal_ranker = SignalRanker()
        self.portfolio_guard = PortfolioGuard()
        self.dynamic_risk_allocator = DynamicRiskAllocator()
        self.recovery_manager = RecoveryManager(database=database, audit_logger=audit_logger, run_id=self.run_id)

    def run(self) -> ForwardShadowSummary:
        opened = 0
        closed = 0
        cycles = 0
        alerts_emitted = 0
        commands_processed = 0
        heartbeat_written = False
        self._audit("FORWARD_SHADOW_STARTED", Severity.INFO, {"execution_attempted": False}, notify=True)
        recovery = self.recovery_manager.recover()
        if recovery.get("status") != "OK":
            self._audit("FORWARD_SHADOW_CRITICAL_ERROR", Severity.CRITICAL, {"reason": "recovery failed", "recovery": recovery, "execution_attempted": False}, notify=True)
            return self._summary(False, 0, 0, 0, 0, heartbeat_written, alerts_emitted, commands_processed)
        if not self._connect():
            self._audit("FORWARD_SHADOW_CRITICAL_ERROR", Severity.CRITICAL, {"execution_attempted": False}, notify=True)
            return self._summary(False, 0, 0, 0, 0, heartbeat_written, alerts_emitted, commands_processed)
        account = self._read_account()
        if account is None:
            self._audit("FORWARD_SHADOW_CRITICAL_ERROR", Severity.CRITICAL, {"reason": "account_info unavailable", "execution_attempted": False}, notify=True)
            return self._summary(True, 0, 0, 0, 0, heartbeat_written, alerts_emitted, commands_processed)
        if self.config.demo_only and not account.is_demo:
            self._audit(
                "ACCOUNT_REAL_DETECTED_READ_ONLY",
                Severity.CRITICAL,
                {"trade_mode": account.trade_mode, "is_demo": account.is_demo, "execution_attempted": False},
                notify=True,
            )
            return self._summary(True, 0, 0, 0, 0, heartbeat_written, alerts_emitted, commands_processed)
        try:
            while self.max_cycles is None or cycles < self.max_cycles:
                commands_processed += self.command_center.poll_and_process() if self.telegram_notifier is not None else 0
                for trade in self.manager.load_open_trades():
                    snapshot = self._snapshot_for(trade.broker_symbol, trade.symbol)
                    if snapshot is None:
                        continue
                    updated = self.manager.update_with_snapshot(trade, snapshot)
                    if updated.status == "CLOSED":
                        closed += 1
                        self._audit("PAPER_TRADE_CLOSED", Severity.INFO, updated.to_dict(), symbol=updated.symbol, notify=True)
                shadow_paused = self.database.get_shadow_paused()
                if shadow_paused:
                    self._audit("SHADOW_PAUSED", Severity.INFO, {"reason": self.database.get_operational_state().get("paused_reason", ""), "execution_attempted": False})
                else:
                    opened += self._scan_new_paper_trades(account)
                after_open = len(self.manager.load_open_trades())
                cycles += 1
                heartbeat = self.heartbeat.write(
                    {
                        "mode": "forward-shadow",
                        "mt5_connected": True,
                        "symbols_seen": len(self.symbols),
                        "symbols_rejected": 0,
                        "open_paper_trades": after_open,
                        "closed_paper_trades_today": closed,
                        "last_error": "",
                        "shadow_paused": shadow_paused,
                        "signal_profile_used": self.config.signal_profile,
                        "stable_gate_confirmed": self.stable_gate_confirmed,
                        "stable_gate_decision": self.stable_gate_decision,
                        "execution_attempted": False,
                    }
                )
                heartbeat_written = True
                metrics = {**self.metrics.collect(), "mt5_connected": True, "sqlite_status": "OK", "jsonl_status": "OK"}
                cycle_alerts = self.alerts.evaluate(metrics)
                alerts_emitted += self.alerts.persist(cycle_alerts)
                if cycle_alerts:
                    self._audit("OPERATIONAL_ALERTS", Severity.WARNING, {"alerts": [alert.to_dict() for alert in cycle_alerts], "execution_attempted": False}, notify=True)
                self._maybe_daily_summary()
                self._audit(
                    "HEARTBEAT",
                    Severity.INFO,
                    heartbeat,
                    notify=False,
                )
                self._audit(
                    "FORWARD_SHADOW_CYCLE",
                    Severity.INFO,
                    {
                        "cycle": cycles,
                        "open_trades": after_open,
                        "heartbeat_written": True,
                        "alerts_emitted": alerts_emitted,
                        "telegram_commands_processed": commands_processed,
                        "shadow_paused": shadow_paused,
                        "execution_attempted": False,
                    },
                )
                if self.max_cycles is None and self.cycle_seconds:
                    sleep(self.cycle_seconds)
            trades = self.manager.load_all_trades()
            write_forward_shadow_report(trades, self.report_dir)
            self._audit("FORWARD_SHADOW_STOPPED", Severity.INFO, {"cycles": cycles, "execution_attempted": False}, notify=True)
            return self._summary(True, cycles, len(self.manager.load_open_trades()), opened, closed, heartbeat_written, alerts_emitted, commands_processed)
        except Exception as exc:
            self._audit("FORWARD_SHADOW_CRITICAL_ERROR", Severity.CRITICAL, {"error": str(exc), "execution_attempted": False}, notify=True)
            return self._summary(True, cycles, len(self.manager.load_open_trades()), opened, closed, heartbeat_written, alerts_emitted, commands_processed)

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
    ) -> ForwardShadowSummary:
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
            shadow_paused=self.database.get_shadow_paused(),
            execution_attempted=False,
            signal_profile_used=self.config.signal_profile,
            stable_gate_confirmed=self.stable_gate_confirmed,
            order_send_called=False,
            order_check_called=False,
        )

    def _connect(self) -> bool:
        self.connector = MT5Connector(config=self.config, mt5_client=self.mt5_client)
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
        is_demo = self.connector._is_demo_trade_mode(trade_mode_raw)
        return AccountState(
            login=getattr(raw, "login", None),
            trade_mode="DEMO" if is_demo else str(trade_mode_raw or "UNKNOWN"),
            balance=float(getattr(raw, "balance", 0.0) or 0.0),
            equity=float(getattr(raw, "equity", 0.0) or 0.0),
            margin_free=float(getattr(raw, "margin_free", 0.0) or 0.0),
            currency=str(getattr(raw, "currency", "USD") or "USD"),
            is_demo=is_demo,
            trade_allowed=bool(getattr(raw, "trade_allowed", False)),
        )

    def _scan_new_paper_trades(self, account: AccountState) -> int:
        assert self.connector is not None
        helper = MT5DataOnlyBot(
            config=self.config,
            symbols=self.symbols,
            audit_logger=self.audit_logger,
            database=self.database,
            telegram_notifier=self.telegram_notifier,
            mt5_client=self.connector.mt5,
            run_id=self.run_id,
        )
        helper.connector = self.connector
        opened = 0
        for canonical_symbol in self.symbols:
            try:
                resolution_check, resolution = self.connector.resolve_symbol(canonical_symbol)
                if not resolution_check.accepted or resolution is None:
                    self._audit("SYMBOL_REJECTED", Severity.WARNING, resolution_check.payload, symbol=canonical_symbol, notify=True)
                    continue
                snapshot = self._snapshot_for(resolution.broker_symbol, resolution.canonical_symbol)
                if snapshot is None:
                    continue
                bars_by_tf = helper._read_timeframes(resolution.canonical_symbol, resolution.broker_symbol, snapshot)
                if bars_by_tf is None:
                    continue
                try:
                    features = helper._features_from_bars(bars_by_tf["M5"], snapshot)
                except Exception as exc:
                    feature_error = self._feature_build_error_payload(
                        resolution.canonical_symbol,
                        exc,
                        bars_by_tf.get("M5"),
                    )
                    self._audit("FORWARD_FEATURE_BUILD_FAILED", Severity.WARNING, feature_error, symbol=resolution.canonical_symbol)
                    self._audit(
                        "FORWARD_NO_SIGNAL_DIAGNOSTIC",
                        Severity.INFO,
                        {
                            "symbol": resolution.canonical_symbol,
                            "no_signal_reason": feature_error["feature_build_error_type"],
                            "feature_error": feature_error,
                            "execution_attempted": False,
                        },
                        symbol=resolution.canonical_symbol,
                    )
                    continue
                if "market_structure" in features:
                    self._audit("MARKET_STRUCTURE_DETECTED", Severity.INFO, dict(features.get("market_structure") or {}), symbol=resolution.canonical_symbol)
                if "liquidity" in features and str(dict(features.get("liquidity") or {}).get("sweep_direction", "NONE")) != "NONE":
                    self._audit("LIQUIDITY_SWEEP_DETECTED", Severity.INFO, dict(features.get("liquidity") or {}), symbol=resolution.canonical_symbol)
                if "session_levels" in features:
                    self._audit("SESSION_LEVEL_CONTEXT", Severity.INFO, dict(features.get("session_levels") or {}), symbol=resolution.canonical_symbol)
                strategy_signal = evaluate_ensemble(snapshot, features, mode="shadow")
                candidate_payload = self._forward_candidate_payload(resolution.canonical_symbol, strategy_signal, features)
                self._audit("FORWARD_CANDIDATE_EVALUATED", Severity.INFO, candidate_payload, symbol=resolution.canonical_symbol)
                if "component_scores" in strategy_signal.metadata:
                    self._audit("STRATEGY_COMPONENT_SCORE", Severity.INFO, {"component_scores": dict(strategy_signal.metadata.get("component_scores", {})), "setup_quality": strategy_signal.metadata.get("setup_quality"), "execution_attempted": False}, symbol=resolution.canonical_symbol)
                if strategy_signal.action == SignalAction.NONE and strategy_signal.metadata.get("blocking_reasons"):
                    self._audit("STRATEGY_BLOCKED_BY_CONTEXT", Severity.INFO, {"blocking_reasons": strategy_signal.metadata.get("blocking_reasons"), "execution_attempted": False}, symbol=resolution.canonical_symbol)
                self._audit(
                    "SIGNAL_DETECTED",
                    Severity.INFO,
                    {
                        "action": strategy_signal.action.value,
                        "score": strategy_signal.score,
                        "reasons": strategy_signal.reasons,
                    },
                    symbol=resolution.canonical_symbol,
                    notify=True,
                )
                if strategy_signal.action == SignalAction.NONE:
                    self._audit("FORWARD_CANDIDATE_BLOCKED", Severity.INFO, candidate_payload, symbol=resolution.canonical_symbol)
                    if candidate_payload.get("near_miss"):
                        self._audit("FORWARD_NEAR_MISS", Severity.INFO, candidate_payload, symbol=resolution.canonical_symbol)
                    self._audit("FORWARD_NO_SIGNAL_DIAGNOSTIC", Severity.INFO, {"symbol": resolution.canonical_symbol, "no_signal_reason": candidate_payload.get("top_blocking_reason", "NO_SETUP_DETECTED"), "candidate": candidate_payload, "execution_attempted": False}, symbol=resolution.canonical_symbol)
                    self._audit(
                        "SIGNAL_REJECTED",
                        Severity.INFO,
                        {"reject_reason": "strategy returned NONE", "reasons": strategy_signal.reasons},
                        symbol=resolution.canonical_symbol,
                        notify=True,
                    )
                    continue
                trade_signal = helper._trade_signal_from_strategy(snapshot, strategy_signal)
                risk_decision = helper.risk_engine.evaluate(
                    signal=trade_signal,
                    snapshot=snapshot,
                    account=account,
                    state=RiskRuntimeState(
                        daily_equity_reference=account.balance,
                        floating_drawdown_reference=account.balance,
                        audit_confirmed=True,
                    ),
                )
                if not risk_decision.accepted:
                    self._audit(
                        "RISK_REJECTED",
                        Severity.WARNING,
                        {
                            "reject_code": risk_decision.reject_code,
                            "reject_reason": risk_decision.reject_reason,
                            "checks": dict(risk_decision.checks),
                        },
                        symbol=resolution.canonical_symbol,
                        notify=True,
                    )
                    continue
                ml_features = {**features, "score": strategy_signal.score}
                ml_decision = self.ml_filter.approve_or_reject(trade_signal, ml_features)
                prediction_payload = {
                    "signal_id": trade_signal.signal_id,
                    "symbol": trade_signal.symbol,
                    "timestamp_utc": trade_signal.created_at_utc.isoformat(),
                    **ml_decision.to_dict(),
                }
                audit_ml_prediction(self.database, prediction_payload)
                self._audit("ML_PREDICTION", Severity.INFO if ml_decision.ml_status != "ML_ERROR" else Severity.ERROR, prediction_payload, symbol=resolution.canonical_symbol)
                if ml_decision.ml_status == "ML_REJECTED":
                    self._audit(
                        "SIGNAL_REJECTED",
                        Severity.INFO,
                        {"reject_reason": "ML_REJECTED", "ml": ml_decision.to_dict(), "execution_attempted": False},
                        symbol=resolution.canonical_symbol,
                        notify=True,
                    )
                    continue
                open_trade_payloads = [trade.to_dict() for trade in self.manager.load_open_trades()]
                risk_pct = self._risk_pct_from_decision(risk_decision, account)
                candidate = {
                    "symbol": trade_signal.symbol,
                    "broker_symbol": resolution.broker_symbol,
                    "direction": trade_signal.direction.value,
                    "risk_pct": risk_pct,
                    "strategy_name": strategy_signal.strategy_name,
                    "regime": str(features.get("regime", "")),
                    "session": str(features.get("session", "")),
                    "strategy_score": strategy_signal.score,
                    "ml_probability": ml_decision.probability_of_success,
                    "spread_percentile": min(100.0, snapshot.spread_points / max(1.0, self.config.max_spread_points_default) * 100.0),
                    "broker_readiness_score": 100.0,
                    "research_candidate_status": str(strategy_signal.metadata.get("candidate_status", "")),
                }
                ranked = self.signal_ranker.rank([candidate], top_n=1)[0]
                self._audit("SIGNAL_RANKED", Severity.INFO, ranked, symbol=resolution.canonical_symbol)
                if ranked["ranking_decision"] != "ACCEPT_TOP_N":
                    self._audit(
                        "SIGNAL_REJECTED",
                        Severity.INFO,
                        {"reject_reason": ranked["ranking_decision"], "ranking": ranked, "execution_attempted": False},
                        symbol=resolution.canonical_symbol,
                        notify=True,
                    )
                    continue
                portfolio_decision = self.portfolio_guard.evaluate(
                    candidate=ranked,
                    open_trades=open_trade_payloads,
                    correlation=ranked.get("correlation"),
                    shadow_paused=self.database.get_shadow_paused(),
                    daily_drawdown_pct=abs(float(risk_decision.daily_drawdown_pct or 0.0)),
                    consecutive_losses=self._consecutive_paper_losses(),
                )
                self._audit("PORTFOLIO_DECISION", Severity.INFO if portfolio_decision.accepted else Severity.WARNING, portfolio_decision.to_dict(), symbol=resolution.canonical_symbol)
                if not portfolio_decision.accepted:
                    event_type = "PORTFOLIO_REJECTED"
                    if "CORRELATION" in portfolio_decision.reject_code:
                        event_type = "CORRELATION_REJECTED"
                    elif "EXPOSURE" in portfolio_decision.reject_code:
                        event_type = "EXPOSURE_REJECTED"
                    self._audit(event_type, Severity.WARNING, portfolio_decision.to_dict(), symbol=resolution.canonical_symbol, notify=True)
                    continue
                dynamic_decision = self.dynamic_risk_allocator.allocate(
                    {
                        **portfolio_decision.checks,
                        "drawdown_pct": abs(float(risk_decision.daily_drawdown_pct or 0.0)),
                        "consecutive_losses": self._consecutive_paper_losses(),
                        "spread_ratio": snapshot.spread_points / max(1.0, self.config.max_spread_points_default),
                        "broker_readiness_score": ranked.get("broker_readiness_score", 100.0),
                        "ml_probability": ml_decision.probability_of_success,
                        "correlation": ranked.get("correlation", 0.0),
                        "symbol_watchlist": str(ranked.get("research_candidate_status", "")).upper() == "WATCHLIST",
                    }
                )
                self._audit("DYNAMIC_RISK_ADJUSTED", Severity.INFO, dynamic_decision.to_dict(), symbol=resolution.canonical_symbol)
                if dynamic_decision.risk_multiplier <= 0:
                    self._audit(
                        "RISK_REJECTED",
                        Severity.WARNING,
                        {
                            "reject_code": "DYNAMIC_RISK_ZERO",
                            "reject_reason": "dynamic risk allocator reduced risk to zero",
                            "dynamic_risk": dynamic_decision.to_dict(),
                            "execution_attempted": False,
                        },
                        symbol=resolution.canonical_symbol,
                        notify=True,
                    )
                    continue
                risk_decision = self._adjust_risk_decision(
                    risk_decision,
                    multiplier=dynamic_decision.risk_multiplier,
                    effective_risk_pct=risk_pct * dynamic_decision.risk_multiplier,
                    portfolio_decision=portfolio_decision.to_dict(),
                    dynamic_risk=dynamic_decision.to_dict(),
                )
                before = self.database.count_rows("paper_trades")
                trade = self.manager.open_trade(
                    signal=trade_signal,
                    risk_decision=risk_decision,
                    snapshot=snapshot,
                    broker_symbol=resolution.broker_symbol,
                    score=strategy_signal.score,
                    reasons=strategy_signal.reasons,
                    strategy_name=strategy_signal.strategy_name,
                    strategy_version=str(strategy_signal.metadata.get("version", "0.1.0")),
                    regime=str(features.get("regime", "")),
                    session=str(features.get("session", "")),
                )
                trade = self._decorate_stable_trade(trade, strategy_signal, features)
                after = self.database.count_rows("paper_trades")
                if after > before:
                    opened += 1
                    self._audit("PAPER_TRADE_OPENED", Severity.INFO, trade.to_dict(), symbol=trade.symbol, notify=True)
            except Exception as exc:
                self._audit(
                    "PAPER_TRADE_ERROR",
                    Severity.ERROR,
                    {"symbol": canonical_symbol, "error": str(exc), "execution_attempted": False},
                    symbol=canonical_symbol,
                    notify=True,
                )
        return opened

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
        if self.config.signal_profile != "BALANCED_STABLE":
            return trade
        effective = effective_profile_config("BALANCED_STABLE", source="forward-shadow", profile_config=self.config.profile_config or None)
        metadata = {
            **dict(trade.metadata),
            "profile": "BALANCED_STABLE",
            "signal_profile_used": "BALANCED_STABLE",
            "stable_profile_hash": effective.profile_hash,
            "stable_filters_applied": bool(effective.filters.get("apply_stability_filters", False)),
            "stable_gate_decision": self.stable_gate_decision,
            "stable_gate_confirmed": self.stable_gate_confirmed,
            "setup_score": strategy_signal.metadata.get("setup_score", strategy_signal.score),
            "ensemble_score": strategy_signal.score,
            "component_scores": dict(strategy_signal.metadata.get("component_scores", {})),
            "session": str(features.get("session", "")),
            "regime": str(features.get("regime", "")),
        }
        updated = trade.replace(metadata=metadata)
        self.database.update_paper_trade(updated.to_dict())
        self.database.insert_paper_trade_event(updated.paper_trade_id, "STABLE_PROFILE_METADATA_ATTACHED", updated.to_dict())
        return updated

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

    def _risk_pct_from_decision(self, decision: RiskDecision, account: AccountState) -> float:
        if account.equity > 0 and decision.risk_amount_account_currency > 0:
            return min(self.config.max_risk_per_trade_pct, decision.risk_amount_account_currency / account.equity * 100.0)
        return self.config.max_risk_per_trade_pct

    def _adjust_risk_decision(
        self,
        decision: RiskDecision,
        *,
        multiplier: float,
        effective_risk_pct: float,
        portfolio_decision: dict[str, Any],
        dynamic_risk: dict[str, Any],
    ) -> RiskDecision:
        multiplier = max(0.0, min(1.0, multiplier))
        checks = {
            **dict(decision.checks),
            "portfolio_decision": portfolio_decision,
            "dynamic_risk": dynamic_risk,
            "effective_risk_pct": effective_risk_pct,
        }
        return RiskDecision(
            signal_id=decision.signal_id,
            accepted=decision.accepted,
            reject_code=decision.reject_code,
            reject_reason=decision.reject_reason,
            approved_lot=decision.approved_lot * multiplier,
            risk_amount_account_currency=decision.risk_amount_account_currency * multiplier,
            open_risk_pct_after_trade=decision.open_risk_pct_after_trade * multiplier,
            daily_drawdown_pct=decision.daily_drawdown_pct,
            floating_drawdown_pct=decision.floating_drawdown_pct,
            checks=checks,
        )

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
        check, snapshot = self.connector.ensure_symbol_snapshot(broker_symbol, canonical_symbol=canonical_symbol, source="forward-shadow")
        if not check.accepted:
            self._audit("SYMBOL_REJECTED", Severity.WARNING, check.payload, symbol=canonical_symbol)
            return None
        if check.payload.get("timestamp_normalized"):
            event_type = "STABLE_TICK_TIME_NORMALIZED" if self.config.signal_profile == "BALANCED_STABLE" else "TICK_TIME_NORMALIZED"
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
        event = Event.create(
            run_id=self.run_id,
            environment=Environment.DEMO,
            severity=severity,
            module="forward_shadow",
            event_type=event_type,
            message=event_type.lower(),
            correlation_id=f"{self.run_id}:{event_type}",
            symbol=symbol,
            payload=payload,
        )
        self.audit_logger.append_event(event)
        self.database.insert_event(event)
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
                    correlation_id=f"{self.run_id}:telegram",
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
