"""Forward shadow observation loop."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from time import sleep
from typing import Any, Iterable
from uuid import uuid4

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import AccountState, Environment, Event, Severity, SignalAction
from agi_style_forex_bot_mt5.execution import MT5Connector
from agi_style_forex_bot_mt5.mt5_data_bot import MT5DataOnlyBot
from agi_style_forex_bot_mt5.ml import MLFilter
from agi_style_forex_bot_mt5.ml.prediction_audit import audit_ml_prediction
from agi_style_forex_bot_mt5.observability import AlertRuleEngine, DailySummary, HeartbeatWriter, MetricsCollector
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

    def run(self) -> ForwardShadowSummary:
        opened = 0
        closed = 0
        cycles = 0
        alerts_emitted = 0
        commands_processed = 0
        heartbeat_written = False
        self._audit("FORWARD_SHADOW_STARTED", Severity.INFO, {"execution_attempted": False}, notify=True)
        if not self._connect():
            self._audit("FORWARD_SHADOW_CRITICAL_ERROR", Severity.CRITICAL, {"execution_attempted": False}, notify=True)
            return ForwardShadowSummary("forward-shadow", False, 0, 0, 0, 0, heartbeat_written, alerts_emitted, commands_processed, self.database.get_shadow_paused(), False)
        account = self._read_account()
        if account is None:
            self._audit("FORWARD_SHADOW_CRITICAL_ERROR", Severity.CRITICAL, {"reason": "account_info unavailable", "execution_attempted": False}, notify=True)
            return ForwardShadowSummary("forward-shadow", True, 0, 0, 0, 0, heartbeat_written, alerts_emitted, commands_processed, self.database.get_shadow_paused(), False)
        if self.config.demo_only and not account.is_demo:
            self._audit(
                "ACCOUNT_REAL_DETECTED_READ_ONLY",
                Severity.CRITICAL,
                {"trade_mode": account.trade_mode, "is_demo": account.is_demo, "execution_attempted": False},
                notify=True,
            )
            return ForwardShadowSummary("forward-shadow", True, 0, 0, 0, 0, heartbeat_written, alerts_emitted, commands_processed, self.database.get_shadow_paused(), False)
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
            return ForwardShadowSummary("forward-shadow", True, cycles, len(self.manager.load_open_trades()), opened, closed, heartbeat_written, alerts_emitted, commands_processed, self.database.get_shadow_paused(), False)
        except Exception as exc:
            self._audit("FORWARD_SHADOW_CRITICAL_ERROR", Severity.CRITICAL, {"error": str(exc), "execution_attempted": False}, notify=True)
            return ForwardShadowSummary("forward-shadow", True, cycles, len(self.manager.load_open_trades()), opened, closed, heartbeat_written, alerts_emitted, commands_processed, self.database.get_shadow_paused(), False)

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
                features = helper._features_from_bars(bars_by_tf["M5"], snapshot)
                strategy_signal = evaluate_ensemble(snapshot, features, mode="shadow")
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

    def _snapshot_for(self, broker_symbol: str, canonical_symbol: str):
        assert self.connector is not None
        check, snapshot = self.connector.ensure_symbol_snapshot(broker_symbol, canonical_symbol=canonical_symbol)
        if not check.accepted:
            self._audit("SYMBOL_REJECTED", Severity.WARNING, check.payload, symbol=canonical_symbol)
            return None
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
