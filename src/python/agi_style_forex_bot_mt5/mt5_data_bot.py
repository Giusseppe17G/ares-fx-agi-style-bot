"""MT5 data-only orchestration.

This module reads real MT5 data for research/shadow decisions only. It never
calls `order_send`, never creates real/demo broker orders, and always returns
`execution_attempted=false`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import pandas as pd

from .bot import AuditUnavailableError, _shadow_order_from_payload
from .config import BotConfig
from .contracts import (
    AccountState,
    Direction,
    EntryType,
    Environment,
    Event,
    MarketSnapshot,
    Severity,
    SignalAction,
    TradeSignal,
)
from .data import add_indicators, add_regime_labels, normalize_ohlcv_bars
from .execution import MT5Connector, ShadowExecutionEngine, ShadowOrder
from .market_structure import build_market_structure_features
from .risk import RiskEngine, RiskRuntimeState
from .strategy import evaluate_ensemble
from .telemetry import JsonlAuditLogger, TelegramNotifier, TelemetryDatabase


TIMEFRAMES: tuple[str, ...] = ("M5", "M15", "H1")
DEFAULT_FOREX_SYMBOLS: tuple[str, ...] = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCAD",
    "USDCHF",
    "AUDUSD",
    "EURJPY",
    "NZDUSD",
)


@dataclass(frozen=True)
class MT5DataOnlySummary:
    """Summary printed by `--mode mt5-data`."""

    mode: str
    mt5_connected: bool
    symbols_seen: int
    symbols_rejected: int
    signals_detected: int
    signals_rejected: int
    risk_rejected: int
    shadow_orders_created: int
    execution_attempted: bool = False


@dataclass(frozen=True)
class MT5DiagnoseSummary:
    """Summary printed by `--mode mt5-diagnose`."""

    mode: str
    mt5_connected: bool
    symbols_seen: int
    symbols_rejected: int
    diagnostics: tuple[dict[str, Any], ...]
    execution_attempted: bool = False


class MT5DataOnlyBot:
    """Read MT5 data, create audited shadow orders, and never execute orders."""

    def __init__(
        self,
        *,
        config: BotConfig | None = None,
        symbols: Sequence[str] = DEFAULT_FOREX_SYMBOLS,
        bars: int = 260,
        audit_logger: JsonlAuditLogger | None = None,
        database: TelemetryDatabase | None = None,
        telegram_notifier: TelegramNotifier | None = None,
        mt5_client: Any | None = None,
        risk_engine: RiskEngine | None = None,
        shadow_execution_engine: ShadowExecutionEngine | None = None,
        run_id: str | None = None,
    ) -> None:
        self.config = config or BotConfig()
        self.config.validate_safety()
        if audit_logger is None or database is None:
            raise AuditUnavailableError("mt5-data mode requires JSONL and SQLite audit sinks")
        self.symbols = tuple(symbol.strip().upper() for symbol in symbols if symbol.strip())
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        self.bars = max(int(bars), 220)
        self.audit_logger = audit_logger
        self.database = database
        self.telegram_notifier = telegram_notifier
        self.mt5_client = mt5_client
        self.connector: MT5Connector | None = None
        self.risk_engine = risk_engine or RiskEngine(self.config)
        self.shadow_execution_engine = shadow_execution_engine or ShadowExecutionEngine()
        self.run_id = run_id or f"run_{uuid4().hex}"

    def run(self) -> MT5DataOnlySummary:
        """Run one MT5 data-only pass and return a safe summary."""

        counters = {
            "symbols_seen": 0,
            "symbols_rejected": 0,
            "signals_detected": 0,
            "signals_rejected": 0,
            "risk_rejected": 0,
            "shadow_orders_created": 0,
        }
        self._audit(
            severity=Severity.INFO,
            module="bot",
            event_type="BOT_STARTED",
            message="mt5-data run started",
            correlation_id=self.run_id,
            payload={"mode": "mt5-data", "symbols": self.symbols},
            notify=True,
        )

        if not self._connect_mt5():
            self._audit_bot_stopped(counters, mt5_connected=False)
            return self._summary(counters, mt5_connected=False)

        account = self._read_account()
        if account is None:
            self._audit_bot_stopped(counters, mt5_connected=True)
            return self._summary(counters, mt5_connected=True)
        self._audit_account_snapshot(account)
        if self.config.demo_only and not account.is_demo:
            self._audit(
                severity=Severity.CRITICAL,
                module="account",
                event_type="ACCOUNT_REAL_DETECTED_READ_ONLY",
                message="real account detected in mt5-data read-only mode; stopping before signals",
                correlation_id=self.run_id,
                payload={
                    "trade_mode": account.trade_mode,
                    "is_demo": account.is_demo,
                    "execution_attempted": False,
                },
                notify=True,
            )
            self._audit_bot_stopped(counters, mt5_connected=True)
            return self._summary(counters, mt5_connected=True)

        for canonical_symbol in self.symbols:
            counters["symbols_seen"] += 1
            try:
                accepted = self._process_symbol(canonical_symbol, account, counters)
                if not accepted:
                    counters["symbols_rejected"] += 1
            except Exception as exc:
                counters["symbols_rejected"] += 1
                self._audit(
                    severity=Severity.ERROR,
                    module="mt5_data",
                    event_type="SYMBOL_REJECTED",
                    message=str(exc),
                    correlation_id=f"{self.run_id}:{canonical_symbol}",
                    symbol=canonical_symbol,
                    payload={"reject_code": "INTERNAL_ERROR", "reject_reason": str(exc)},
                    notify=True,
                )

        self._audit_bot_stopped(counters, mt5_connected=True)
        return self._summary(counters, mt5_connected=True)

    def _connect_mt5(self) -> bool:
        try:
            self.connector = MT5Connector(config=self.config, mt5_client=self.mt5_client)
            initialize = getattr(self.connector.mt5, "initialize", None)
            if callable(initialize) and initialize() is not True:
                self._audit(
                    severity=Severity.CRITICAL,
                    module="mt5",
                    event_type="MT5_CONNECTION_FAILED",
                    message="MT5 initialize failed",
                    correlation_id=self.run_id,
                    payload={"last_error": self.connector.last_error_code()},
                    notify=True,
                )
                return False
            self._audit(
                severity=Severity.INFO,
                module="mt5",
                event_type="MT5_CONNECTED",
                message="MT5 connected for data-only read",
                correlation_id=self.run_id,
                payload={"read_only": True, "execution_attempted": False},
                notify=True,
            )
            return True
        except Exception as exc:
            self._audit(
                severity=Severity.CRITICAL,
                module="mt5",
                event_type="MT5_CONNECTION_FAILED",
                message=str(exc),
                correlation_id=self.run_id,
                payload={"error_type": type(exc).__name__},
                notify=True,
            )
            return False

    def _read_account(self) -> AccountState | None:
        assert self.connector is not None
        raw = self.connector.mt5.account_info()
        if raw is None:
            self._audit(
                severity=Severity.CRITICAL,
                module="account",
                event_type="CRITICAL_ERROR",
                message="account_info unavailable",
                correlation_id=self.run_id,
                payload={"reject_code": "ACCOUNT_TYPE_UNKNOWN"},
                notify=True,
            )
            return None
        login = getattr(raw, "login", None)
        trade_mode_raw = getattr(raw, "trade_mode", None)
        is_demo = self.connector._is_demo_trade_mode(trade_mode_raw)
        trade_mode = "DEMO" if is_demo else str(trade_mode_raw or "UNKNOWN")
        return AccountState(
            login=int(login) if login is not None else None,
            trade_mode=trade_mode,
            balance=float(getattr(raw, "balance", 0.0) or 0.0),
            equity=float(getattr(raw, "equity", 0.0) or 0.0),
            margin_free=float(getattr(raw, "margin_free", 0.0) or 0.0),
            currency=str(getattr(raw, "currency", "") or ""),
            is_demo=is_demo,
            trade_allowed=bool(getattr(raw, "trade_allowed", False)),
        )

    def _audit_account_snapshot(self, account: AccountState) -> None:
        assert self.connector is not None
        raw = self.connector.mt5.account_info()
        self._audit(
            severity=Severity.INFO,
            module="account",
            event_type="ACCOUNT_SNAPSHOT",
            message="MT5 account snapshot captured",
            correlation_id=self.run_id,
            payload={
                "login": account.login,
                "server": getattr(raw, "server", None),
                "trade_mode": account.trade_mode,
                "currency": account.currency,
                "balance": account.balance,
                "equity": account.equity,
                "margin": float(getattr(raw, "margin", 0.0) or 0.0),
                "margin_free": account.margin_free,
                "leverage": getattr(raw, "leverage", None),
                "is_demo": account.is_demo,
                "trade_allowed": account.trade_allowed,
            },
            notify=True,
        )

    def _process_symbol(
        self,
        canonical_symbol: str,
        account: AccountState,
        counters: dict[str, int],
    ) -> bool:
        assert self.connector is not None
        resolution_check, resolution = self.connector.resolve_symbol(canonical_symbol)
        if not resolution_check.accepted or resolution is None:
            self._symbol_rejected(
                canonical_symbol,
                resolution_check.code,
                resolution_check.reason,
                resolution_check.payload,
            )
            return False
        broker_symbol = resolution.broker_symbol
        check, snapshot = self.connector.ensure_symbol_snapshot(
            broker_symbol,
            canonical_symbol=resolution.canonical_symbol,
            source="mt5-data",
        )
        if not check.accepted or snapshot is None:
            self._symbol_rejected(canonical_symbol, check.code, check.reason, check.payload, broker_symbol=broker_symbol)
            return False
        self._audit(
            severity=Severity.INFO,
            module="mt5",
            event_type="SYMBOL_ACCEPTED",
            message="symbol snapshot accepted",
            correlation_id=f"{self.run_id}:{canonical_symbol}",
            symbol=canonical_symbol,
            payload={
                "canonical_symbol": canonical_symbol,
                "broker_symbol": broker_symbol,
                "spread_points": snapshot.spread_points,
                "digits": snapshot.digits,
                "point": snapshot.point,
                "volume_min": snapshot.volume_min,
                "volume_max": snapshot.volume_max,
                "volume_step": snapshot.volume_step,
                "stops_level_points": snapshot.stops_level_points,
                "freeze_level_points": snapshot.freeze_level_points,
            },
        )
        bars_by_tf = self._read_timeframes(canonical_symbol, broker_symbol, snapshot)
        if bars_by_tf is None:
            return False
        features = self._features_from_bars(bars_by_tf["M5"], snapshot)
        strategy_signal = evaluate_ensemble(snapshot, features, mode="shadow")
        counters["signals_detected"] += 1
        self._audit(
            severity=Severity.INFO,
            module="strategy",
            event_type="SIGNAL_DETECTED",
            message=f"strategy emitted {strategy_signal.action.value}",
            correlation_id=f"{self.run_id}:{canonical_symbol}:signal",
            symbol=canonical_symbol,
            payload={
                "action": strategy_signal.action.value,
                "score": strategy_signal.score,
                "reasons": strategy_signal.reasons,
                "features": features,
            },
            notify=True,
        )
        if strategy_signal.action == SignalAction.NONE:
            counters["signals_rejected"] += 1
            self._audit(
                severity=Severity.INFO,
                module="strategy",
                event_type="SIGNAL_REJECTED",
                message="strategy returned NONE",
                correlation_id=f"{self.run_id}:{canonical_symbol}:signal",
                symbol=canonical_symbol,
                payload={"reasons": strategy_signal.reasons},
                notify=True,
            )
            return True
        try:
            trade_signal = self._trade_signal_from_strategy(snapshot, strategy_signal)
        except ValueError as exc:
            counters["signals_rejected"] += 1
            self._audit(
                severity=Severity.WARNING,
                module="strategy",
                event_type="SIGNAL_REJECTED",
                message=str(exc),
                correlation_id=f"{self.run_id}:{canonical_symbol}:signal",
                symbol=canonical_symbol,
                payload={"reject_code": "INVALID_SIGNAL", "reject_reason": str(exc)},
                notify=True,
            )
            return True
        self._audit(
            severity=Severity.INFO,
            module="strategy",
            event_type="TRADE_SIGNAL_CREATED",
            message="trade signal candidate created from MT5 data",
            correlation_id=trade_signal.signal_id,
            signal_id=trade_signal.signal_id,
            symbol=canonical_symbol,
            payload={
                "direction": trade_signal.direction.value,
                "sl_price": trade_signal.sl_price,
                "tp_price": trade_signal.tp_price,
                "confidence": trade_signal.confidence,
            },
        )
        risk_decision = self.risk_engine.evaluate(
            signal=trade_signal,
            snapshot=snapshot,
            account=account,
            state=RiskRuntimeState(
                daily_equity_reference=account.balance,
                floating_drawdown_reference=account.balance,
                audit_confirmed=True,
            ),
        )
        self._audit(
            severity=Severity.INFO if risk_decision.accepted else Severity.WARNING,
            module="risk",
            event_type="SIGNAL_ACCEPTED" if risk_decision.accepted else "RISK_REJECTED",
            message="risk accepted signal" if risk_decision.accepted else risk_decision.reject_reason,
            correlation_id=trade_signal.signal_id,
            signal_id=trade_signal.signal_id,
            symbol=canonical_symbol,
            payload={
                "accepted": risk_decision.accepted,
                "reject_code": risk_decision.reject_code,
                "reject_reason": risk_decision.reject_reason,
                "approved_lot": risk_decision.approved_lot,
                "checks": dict(risk_decision.checks),
            },
            notify=not risk_decision.accepted,
        )
        if not risk_decision.accepted:
            counters["risk_rejected"] += 1
            return True
        shadow_order = self.shadow_execution_engine.create_order(
            signal=trade_signal,
            risk_decision=risk_decision,
            snapshot=snapshot,
            strategy_score=strategy_signal.score,
            reasons=tuple(strategy_signal.reasons),
        )
        shadow_order = self._persist_shadow_order(shadow_order)
        counters["shadow_orders_created"] += 1
        self._audit(
            severity=Severity.INFO,
            module="execution",
            event_type="SHADOW_ORDER_CREATED",
            message="MT5 data-only shadow order created; order_send not called",
            correlation_id=trade_signal.signal_id,
            signal_id=trade_signal.signal_id,
            symbol=canonical_symbol,
            payload=shadow_order.as_record(),
            notify=True,
        )
        return True

    def _read_timeframes(
        self,
        canonical_symbol: str,
        broker_symbol: str,
        snapshot: MarketSnapshot,
    ) -> dict[str, pd.DataFrame] | None:
        assert self.connector is not None
        frames: dict[str, pd.DataFrame] = {}
        for timeframe in TIMEFRAMES:
            const_name = f"TIMEFRAME_{timeframe}"
            mt5_timeframe = getattr(self.connector.mt5, const_name, timeframe)
            raw = self.connector.mt5.copy_rates_from_pos(broker_symbol, mt5_timeframe, 0, self.bars)
            if raw is None or len(raw) == 0:
                self._audit(
                    severity=Severity.WARNING,
                    module="mt5_data",
                    event_type="MT5_RATES_EMPTY",
                    message=f"{timeframe} copy_rates_from_pos returned no data",
                    correlation_id=f"{self.run_id}:{canonical_symbol}:{timeframe}:rates_empty",
                    symbol=canonical_symbol,
                    payload={
                        "canonical_symbol": canonical_symbol,
                        "broker_symbol": broker_symbol,
                        "timeframe": timeframe,
                        "source": "copy_rates_from_pos",
                        "mt5_last_error": self.connector.last_error_payload(),
                    },
                )
                raw = self._copy_rates_range_fallback(broker_symbol, mt5_timeframe, timeframe)
            if raw is None or len(raw) == 0:
                self._symbol_rejected(
                    canonical_symbol,
                    "MARKET_DATA_REJECTED",
                    f"{timeframe} market data is empty",
                    {
                        "canonical_symbol": canonical_symbol,
                        "broker_symbol": broker_symbol,
                        "timeframe": timeframe,
                        "fallback_attempted": True,
                        "mt5_last_error": self.connector.last_error_payload(),
                    },
                    broker_symbol=broker_symbol,
                )
                return None
            try:
                frame = normalize_ohlcv_bars(raw, symbol=canonical_symbol, timeframe=timeframe)
                if "spread_points" not in frame.columns:
                    frame["spread_points"] = snapshot.spread_points
                if len(frame) < 220:
                    raise ValueError(f"{timeframe} has insufficient bars: {len(frame)}")
                frames[timeframe] = frame
                self._audit(
                    severity=Severity.INFO,
                    module="mt5_data",
                    event_type="MARKET_DATA_READ",
                    message=f"{timeframe} rates read",
                    correlation_id=f"{self.run_id}:{canonical_symbol}:{timeframe}",
                    symbol=canonical_symbol,
                    payload={
                        "canonical_symbol": canonical_symbol,
                        "broker_symbol": broker_symbol,
                        "timeframe": timeframe,
                        "bars": len(frame),
                    },
                )
            except Exception as exc:
                self._symbol_rejected(
                    canonical_symbol,
                    "MARKET_DATA_REJECTED",
                    str(exc),
                    {
                        "canonical_symbol": canonical_symbol,
                        "broker_symbol": broker_symbol,
                        "timeframe": timeframe,
                    },
                    broker_symbol=broker_symbol,
                )
                return None
        return frames

    def _copy_rates_range_fallback(self, broker_symbol: str, mt5_timeframe: Any, timeframe: str) -> Any:
        assert self.connector is not None
        copy_rates_range = getattr(self.connector.mt5, "copy_rates_range", None)
        if not callable(copy_rates_range):
            return None
        minutes = {"M5": 5, "M15": 15, "H1": 60}.get(timeframe, 5)
        date_to = datetime.now(timezone.utc)
        date_from = date_to - timedelta(minutes=minutes * (self.bars + 10))
        return copy_rates_range(broker_symbol, mt5_timeframe, date_from, date_to)

    def _features_from_bars(
        self,
        bars: pd.DataFrame,
        snapshot: MarketSnapshot,
    ) -> dict[str, Any]:
        with_indicators = add_indicators(bars)
        labeled = add_regime_labels(
            with_indicators,
            max_spread_points=self.config.max_spread_points_default,
        )
        latest = labeled.iloc[-1]
        critical = [
            "ema20",
            "ema50",
            "ema200",
            "rsi14",
            "atr14",
            "atr_percent",
            "ema_slope",
            "trend_strength",
            "momentum",
            "volatility",
        ]
        if latest[critical].isna().any():
            missing = [name for name in critical if pd.isna(latest[name])]
            raise ValueError(f"critical indicator values missing: {', '.join(missing)}")
        previous_close = float(labeled.iloc[-2]["close"]) if len(labeled) > 1 else float(latest["close"])
        high_window = labeled.tail(20)["high"]
        low_window = labeled.tail(20)["low"]
        close = float(latest["close"])
        structure_features = build_market_structure_features(labeled, point=snapshot.point)
        return {
            **structure_features,
            "regime": str(latest["regime"]),
            "close": close,
            "previous_close": previous_close,
            "ema20": float(latest["ema20"]),
            "ema50": float(latest["ema50"]),
            "ema200": float(latest["ema200"]),
            "ema_fast": float(latest["ema20"]),
            "ema_slow": float(latest["ema50"]),
            "rsi": float(latest["rsi14"]),
            "rsi14": float(latest["rsi14"]),
            "atr": float(latest["atr14"]),
            "atr14": float(latest["atr14"]),
            "atr_points": float(latest["atr14"]) / snapshot.point,
            "atr_mean_points": float(labeled.tail(50)["atr14"].mean()) / snapshot.point,
            "atr_percent": float(latest["atr_percent"]),
            "ema_slope": float(latest["ema_slope"]),
            "trend_slope": float(latest["ema_slope"]),
            "trend_strength": float(latest["trend_strength"]),
            "momentum": float(latest["momentum"]),
            "momentum_points": float(latest["momentum"]) / snapshot.point,
            "range_points": float((high_window.max() - low_window.min()) / snapshot.point),
            "body_ratio": float(abs(latest["candle_body"]) / max(latest["high"] - latest["low"], snapshot.point)),
            "prior_high": float(high_window.iloc[:-1].max()) if len(high_window) > 1 else close,
            "prior_low": float(low_window.iloc[:-1].min()) if len(low_window) > 1 else close,
            "lower_wick": float(latest["lower_wick"]),
            "upper_wick": float(latest["upper_wick"]),
            "spread_points": snapshot.spread_points,
            "max_strategy_spread_points": self.config.max_spread_points_default,
            "session": "LONDON",
            "volatility": float(latest["volatility"]),
        }

    def _trade_signal_from_strategy(self, snapshot: MarketSnapshot, strategy_signal: Any) -> TradeSignal:
        direction = Direction.BUY if strategy_signal.action == SignalAction.BUY else Direction.SELL
        reference = snapshot.ask if direction == Direction.BUY else snapshot.bid
        atr = float(strategy_signal.metadata.get("atr", 0.0) or 0.0)
        stop_distance = max(atr, snapshot.point * 100, snapshot.stops_level_points * snapshot.point * 2)
        take_profit_distance = stop_distance * 1.8
        if direction == Direction.BUY:
            sl_price = reference - stop_distance
            tp_price = reference + take_profit_distance
        else:
            sl_price = reference + stop_distance
            tp_price = reference - take_profit_distance
        signal = TradeSignal(
            signal_id=TradeSignal.new_id(),
            created_at_utc=snapshot.timestamp_utc,
            symbol=snapshot.symbol,
            timeframe="M5",
            direction=direction,
            entry_type=EntryType.MARKET,
            sl_price=round(sl_price, snapshot.digits),
            tp_price=round(tp_price, snapshot.digits),
            risk_pct=self.config.max_risk_per_trade_pct,
            confidence=min(1.0, max(0.0, strategy_signal.score / 100)),
            strategy_name=strategy_signal.strategy_name,
            strategy_version=str(strategy_signal.metadata.get("version", "0.1.0")),
            reason="; ".join(strategy_signal.reasons),
            metadata=dict(strategy_signal.metadata),
        )
        signal.validate_against_snapshot(snapshot)
        return signal

    def _persist_shadow_order(self, shadow_order: ShadowOrder) -> ShadowOrder:
        inserted = self.database.insert_record(
            "orders",
            shadow_order.as_record(),
            idempotency_key=shadow_order.idempotency_key,
        )
        if not inserted:
            existing = self.database.fetch_by_idempotency_key("orders", shadow_order.idempotency_key)
            if existing is not None:
                return _shadow_order_from_payload(existing["payload_json"])
        return shadow_order

    def _symbol_rejected(
        self,
        symbol: str,
        reject_code: str,
        reject_reason: str,
        payload: Mapping[str, Any] | None = None,
        *,
        broker_symbol: str | None = None,
    ) -> None:
        self._audit(
            severity=Severity.WARNING,
            module="mt5_data",
            event_type="SYMBOL_REJECTED",
            message=reject_reason,
            correlation_id=f"{self.run_id}:{symbol}",
            symbol=symbol,
            payload={
                "symbol": symbol,
                "canonical_symbol": symbol,
                "broker_symbol": broker_symbol or dict(payload or {}).get("broker_symbol") or symbol,
                "reject_code": reject_code,
                "reject_reason": reject_reason,
                **dict(payload or {}),
            },
            notify=True,
        )

    def _audit_bot_stopped(self, counters: Mapping[str, int], *, mt5_connected: bool) -> None:
        self._audit(
            severity=Severity.INFO,
            module="bot",
            event_type="BOT_STOPPED",
            message="mt5-data run stopped",
            correlation_id=self.run_id,
            payload={**dict(counters), "mt5_connected": mt5_connected, "execution_attempted": False},
            notify=True,
        )

    def _summary(self, counters: Mapping[str, int], *, mt5_connected: bool) -> MT5DataOnlySummary:
        return MT5DataOnlySummary(
            mode="mt5-data",
            mt5_connected=mt5_connected,
            symbols_seen=int(counters["symbols_seen"]),
            symbols_rejected=int(counters["symbols_rejected"]),
            signals_detected=int(counters["signals_detected"]),
            signals_rejected=int(counters["signals_rejected"]),
            risk_rejected=int(counters["risk_rejected"]),
            shadow_orders_created=int(counters["shadow_orders_created"]),
            execution_attempted=False,
        )

    def _audit(
        self,
        *,
        severity: Severity,
        module: str,
        event_type: str,
        message: str,
        correlation_id: str,
        payload: Mapping[str, Any],
        signal_id: str | None = None,
        symbol: str | None = None,
        notify: bool = False,
    ) -> Event:
        event = Event.create(
            run_id=self.run_id,
            environment=Environment.DEMO,
            severity=severity,
            module=module,
            event_type=event_type,
            message=message,
            correlation_id=correlation_id,
            payload=payload,
            signal_id=signal_id,
            symbol=symbol,
        )
        self.audit_logger.append_event(event)
        self.database.insert_event(event)
        if notify and self.telegram_notifier is not None:
            try:
                result = self.telegram_notifier.notify_event(event)
                if result.status == "FAILED":
                    self._audit(
                        severity=Severity.ERROR,
                        module="telegram",
                        event_type="TELEGRAM_ERROR",
                        message=result.error or "telegram notification failed",
                        correlation_id=event.correlation_id,
                        payload={"telegram_message_id": result.telegram_message_id},
                        signal_id=signal_id,
                        symbol=symbol,
                        notify=False,
                    )
            except Exception as exc:
                self._audit(
                    severity=Severity.ERROR,
                    module="telegram",
                    event_type="TELEGRAM_ERROR",
                    message=str(exc),
                    correlation_id=event.correlation_id,
                    payload={"error_type": type(exc).__name__},
                    signal_id=signal_id,
                    symbol=symbol,
                    notify=False,
                )
        return event


class MT5DiagnoseBot(MT5DataOnlyBot):
    """Read MT5 account/symbol/tick diagnostics without signals or orders."""

    def run(self) -> MT5DiagnoseSummary:
        """Run one MT5 diagnostic pass and return per-symbol diagnostics."""

        diagnostics: list[dict[str, Any]] = []
        counters = {
            "symbols_seen": 0,
            "symbols_rejected": 0,
            "signals_detected": 0,
            "signals_rejected": 0,
            "risk_rejected": 0,
            "shadow_orders_created": 0,
        }
        self._audit(
            severity=Severity.INFO,
            module="bot",
            event_type="BOT_STARTED",
            message="mt5-diagnose run started",
            correlation_id=self.run_id,
            payload={"mode": "mt5-diagnose", "symbols": self.symbols, "execution_attempted": False},
            notify=True,
        )
        if not self._connect_mt5():
            self._audit_bot_stopped(counters, mt5_connected=False)
            return MT5DiagnoseSummary(
                mode="mt5-diagnose",
                mt5_connected=False,
                symbols_seen=0,
                symbols_rejected=0,
                diagnostics=tuple(diagnostics),
                execution_attempted=False,
            )
        account = self._read_account()
        if account is not None:
            self._audit_account_snapshot(account)
        else:
            self._audit_bot_stopped(counters, mt5_connected=True)
            return MT5DiagnoseSummary(
                mode="mt5-diagnose",
                mt5_connected=True,
                symbols_seen=0,
                symbols_rejected=0,
                diagnostics=tuple(diagnostics),
                execution_attempted=False,
            )

        for canonical_symbol in self.symbols:
            counters["symbols_seen"] += 1
            diagnostic = self._diagnose_symbol(canonical_symbol)
            diagnostics.append(diagnostic)
            if diagnostic["status"] not in {"OK", "PASSED"}:
                counters["symbols_rejected"] += 1

        self._audit_bot_stopped(counters, mt5_connected=True)
        return MT5DiagnoseSummary(
            mode="mt5-diagnose",
            mt5_connected=True,
            symbols_seen=counters["symbols_seen"],
            symbols_rejected=counters["symbols_rejected"],
            diagnostics=tuple(diagnostics),
            execution_attempted=False,
        )

    def _diagnose_symbol(self, canonical_symbol: str) -> dict[str, Any]:
        assert self.connector is not None
        now = datetime.now(timezone.utc)
        resolution_check, resolution = self.connector.resolve_symbol(canonical_symbol)
        if not resolution_check.accepted or resolution is None:
            payload = {
                "symbol": canonical_symbol,
                "canonical_symbol": canonical_symbol,
                "broker_symbol": None,
                "status": "REJECTED",
                "reject_code": resolution_check.code,
                "reject_reason": resolution_check.reason,
                "mt5_last_error": self.connector.last_error_payload(),
                "market_is_probably_closed": False,
                **resolution_check.payload,
            }
            self._audit_diagnostic(payload)
            self._symbol_rejected(canonical_symbol, resolution_check.code, resolution_check.reason, payload)
            return payload

        broker_symbol = resolution.broker_symbol
        check, _snapshot = self.connector.ensure_symbol_snapshot(
            broker_symbol,
            canonical_symbol=resolution.canonical_symbol,
            now_utc=now,
            source="mt5-diagnose",
        )
        symbol_info = self.connector.mt5.symbol_info(broker_symbol)
        tick = self.connector.mt5.symbol_info_tick(broker_symbol)
        freshness = self.connector.tick_freshness(tick, now_utc=now) if tick is not None else None
        point = float(getattr(symbol_info, "point", 0.0) or 0.0) if symbol_info is not None else 0.0
        bid = float(getattr(tick, "bid", 0.0) or 0.0) if tick is not None else 0.0
        ask = float(getattr(tick, "ask", 0.0) or 0.0) if tick is not None else 0.0
        spread_points = (ask - bid) / point if point > 0 and ask >= bid else None
        payload = {
            "symbol": canonical_symbol,
            "canonical_symbol": resolution.canonical_symbol,
            "broker_symbol": broker_symbol,
            "bid": bid,
            "ask": ask,
            "spread_points": spread_points,
            "tick.time": getattr(tick, "time", None) if tick is not None else None,
            "tick.time_msc": getattr(tick, "time_msc", None) if tick is not None else None,
            "tick_time_raw": getattr(tick, "time", None) if tick is not None else None,
            "tick_time_msc_raw": getattr(tick, "time_msc", None) if tick is not None else None,
            "tick_time_utc": freshness.tick_time_utc.isoformat() if freshness and freshness.tick_time_utc else None,
            "tick_time_msc_utc": freshness.tick_time_msc_utc.isoformat() if freshness and freshness.tick_time_msc_utc else None,
            "tick_time_utc_raw": freshness.tick_time_utc_raw.isoformat() if freshness and freshness.tick_time_utc_raw else None,
            "normalized_tick_utc": freshness.normalized_tick_utc.isoformat() if freshness and freshness.normalized_tick_utc else None,
            "timestamp_normalized": freshness.timestamp_normalized if freshness else False,
            "broker_time_offset_seconds": freshness.broker_time_offset_seconds if freshness else 0,
            "tick_age_seconds_raw": freshness.tick_age_seconds_raw if freshness else None,
            "tick_age_seconds_normalized": freshness.tick_age_seconds_normalized if freshness else None,
            "tick_time_status": freshness.tick_time_status if freshness else "MARKET_CLOSED_OR_NO_TICKS",
            "normalization_reason": freshness.normalization_reason if freshness else "",
            "now_utc": now.isoformat(),
            "tick_age_seconds": freshness.tick_age_seconds if freshness else None,
            "tick_age_seconds_from_time": freshness.tick_age_seconds_from_time if freshness else None,
            "tick_age_seconds_from_time_msc": freshness.tick_age_seconds_from_time_msc if freshness else None,
            "mt5.last_error()": self.connector.last_error_payload(),
            "market_is_probably_closed": bool(check.payload.get("market_is_probably_closed", False)),
            "status": "PASSED" if check.accepted else "REJECTED",
            "reject_code": None if check.accepted else check.code,
            "reject_reason": None if check.accepted else check.reason,
            "execution_attempted": False,
            **check.payload,
        }
        self._audit_diagnostic(payload)
        if not check.accepted:
            self._symbol_rejected(canonical_symbol, check.code, check.reason, payload, broker_symbol=broker_symbol)
        return payload

    def _audit_diagnostic(self, payload: Mapping[str, Any]) -> None:
        symbol = str(payload.get("canonical_symbol") or payload.get("symbol") or "")
        self._audit(
            severity=Severity.INFO if payload.get("status") in {"OK", "PASSED"} else Severity.WARNING,
            module="mt5",
            event_type="MT5_DIAGNOSTIC",
            message=f"MT5 diagnostic {payload.get('status')}",
            correlation_id=f"{self.run_id}:{symbol}:diagnose",
            symbol=symbol,
            payload=payload,
            notify=False,
        )


def summary_to_json(summary: MT5DataOnlySummary | MT5DiagnoseSummary) -> str:
    """Serialize summary as stable JSON."""

    import json

    payload = asdict(summary) if is_dataclass(summary) else vars(summary)
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)
