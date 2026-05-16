"""Read-only MT5 broker quality probe."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import Environment, Event, Severity
from agi_style_forex_bot_mt5.execution import MT5Connector, is_market_probably_closed
from agi_style_forex_bot_mt5.telemetry import JsonlAuditLogger, TelemetryDatabase

from .broker_quality_report import write_broker_quality_report
from .latency_monitor import measure_latency_ms
from .readiness_score import score_symbol_readiness
from .session_quality import classify_session
from .symbol_quality import SymbolQuality


TIMEFRAMES = {"M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1"}


class BrokerQualityProbe:
    """Collect read-only broker/symbol quality metrics."""

    def __init__(
        self,
        *,
        config: BotConfig | None = None,
        symbols: Iterable[str],
        audit_logger: JsonlAuditLogger | None = None,
        database: TelemetryDatabase | None = None,
        mt5_client: Any | None = None,
        bars: int = 260,
        run_id: str | None = None,
    ) -> None:
        self.config = config or BotConfig()
        self.config.validate_safety()
        self.symbols = tuple(symbol.strip().upper() for symbol in symbols if symbol.strip())
        self.audit_logger = audit_logger
        self.database = database
        self.mt5_client = mt5_client
        self.bars = max(1, int(bars))
        self.run_id = run_id or f"broker_quality_{uuid4().hex}"
        self.connector: MT5Connector | None = None

    def run(self) -> dict[str, Any]:
        checked: list[dict[str, Any]] = []
        connected = self._connect()
        if not connected:
            for symbol in self.symbols:
                checked.append(self._not_ready(symbol, "MT5 initialize failed"))
            return self._summary(checked, mt5_connected=False)
        assert self.connector is not None
        _account, account_latency, account_error = measure_latency_ms(lambda: self.connector.mt5.account_info())
        self._audit(
            "BROKER_QUALITY_ACCOUNT_READ",
            Severity.INFO if not account_error else Severity.WARNING,
            {"latency_ms_account_info": account_latency, "error": account_error, "execution_attempted": False},
        )
        for symbol in self.symbols:
            quality = self._probe_symbol(symbol)
            checked.append(quality.to_dict())
            self._audit("BROKER_QUALITY_SYMBOL", Severity.INFO if quality.status != "NOT_READY" else Severity.WARNING, quality.to_dict(), symbol=symbol)
            if self.database is not None:
                self.database.insert_record(
                    "broker_quality",
                    quality.to_dict(),
                    idempotency_key=f"broker_quality:{self.run_id}:{symbol}",
                )
        return self._summary(checked, mt5_connected=True)

    def _connect(self) -> bool:
        try:
            self.connector = MT5Connector(config=self.config, mt5_client=self.mt5_client)
            initialize = getattr(self.connector.mt5, "initialize", None)
            return (not callable(initialize)) or initialize() is True
        except Exception as exc:
            self._audit("BROKER_QUALITY_CONNECTION_FAILED", Severity.CRITICAL, {"error": str(exc), "execution_attempted": False})
            return False

    def _probe_symbol(self, canonical_symbol: str) -> SymbolQuality:
        assert self.connector is not None
        now = datetime.now(timezone.utc)
        resolution_check, resolution = self.connector.resolve_symbol(canonical_symbol)
        if not resolution_check.accepted or resolution is None:
            payload = self._not_ready(canonical_symbol, resolution_check.reason, broker_symbol=canonical_symbol)
            return SymbolQuality(**payload)
        broker_symbol = resolution.broker_symbol
        symbol_info, symbol_latency, symbol_error = measure_latency_ms(lambda: self.connector.mt5.symbol_info(broker_symbol))
        tick, tick_latency, tick_error = measure_latency_ms(lambda: self.connector.mt5.symbol_info_tick(broker_symbol))
        rates_counts, rates_latency, rates_reasons = self._rates_quality(broker_symbol)
        if symbol_info is None:
            payload = self._not_ready(canonical_symbol, symbol_error or "symbol_info unavailable", broker_symbol=broker_symbol)
            payload["read_latency_ms_tick"] = tick_latency
            payload["read_latency_ms_rates"] = rates_latency
            return SymbolQuality(**payload)
        point = float(getattr(symbol_info, "point", 0.0) or 0.0)
        bid = float(getattr(tick, "bid", 0.0) or 0.0) if tick is not None else 0.0
        ask = float(getattr(tick, "ask", 0.0) or 0.0) if tick is not None else 0.0
        spread = (ask - bid) / point if point > 0 and ask >= bid else 0.0
        freshness = self.connector.tick_freshness(tick, now_utc=now) if tick is not None else None
        base = {
            "canonical_symbol": canonical_symbol,
            "broker_symbol": broker_symbol,
            "symbol_visible": bool(getattr(symbol_info, "visible", False)),
            "trade_mode": str(getattr(symbol_info, "trade_mode", "")),
            "trade_allowed": self.connector._symbol_trading_enabled(symbol_info),
            "bid": bid,
            "ask": ask,
            "spread_points": spread,
            "point": point,
            "digits": int(getattr(symbol_info, "digits", 0) or 0),
            "tick_value": float(getattr(symbol_info, "trade_tick_value", 0.0) or 0.0),
            "tick_size": float(getattr(symbol_info, "trade_tick_size", 0.0) or 0.0),
            "trade_contract_size": float(getattr(symbol_info, "trade_contract_size", 0.0) or 0.0),
            "volume_min": float(getattr(symbol_info, "volume_min", 0.0) or 0.0),
            "volume_max": float(getattr(symbol_info, "volume_max", 0.0) or 0.0),
            "volume_step": float(getattr(symbol_info, "volume_step", 0.0) or 0.0),
            "stops_level_points": int(getattr(symbol_info, "trade_stops_level", -1) or -1),
            "freeze_level_points": int(getattr(symbol_info, "trade_freeze_level", -1) or -1),
            "filling_mode": str(getattr(symbol_info, "filling_mode", "")),
            "tick_time_utc": freshness.selected_time_utc.isoformat() if freshness and freshness.selected_time_utc else None,
            "tick_age_seconds": freshness.tick_age_seconds if freshness else None,
            "mt5_last_error": self.connector.last_error_payload(),
            "market_is_probably_closed": is_market_probably_closed(now, canonical_symbol),
            "rates_available_m5": rates_counts["M5"] > 0,
            "rates_available_m15": rates_counts["M15"] > 0,
            "rates_available_h1": rates_counts["H1"] > 0,
            "bars_count_m5": rates_counts["M5"],
            "bars_count_m15": rates_counts["M15"],
            "bars_count_h1": rates_counts["H1"],
            "read_latency_ms_tick": tick_latency,
            "read_latency_ms_rates": rates_latency + symbol_latency,
            "status": "NOT_READY",
            "reasons": tuple(reason for reason in (symbol_error, tick_error, *rates_reasons) if reason),
            "read_session": classify_session(now),
            "execution_attempted": False,
            "order_send_called": False,
        }
        score, status, score_reasons = score_symbol_readiness(base, max_spread_points=self.config.max_spread_points_default)
        reasons = tuple(dict.fromkeys((*base["reasons"], *score_reasons)))
        return SymbolQuality(
            **{
                key: value
                for key, value in base.items()
                if key in SymbolQuality.__dataclass_fields__
                and key not in {"status", "reasons", "readiness_score"}
            },
            status=status,
            reasons=reasons,
            readiness_score=score,
        )

    def _rates_quality(self, broker_symbol: str) -> tuple[dict[str, int], int, list[str]]:
        assert self.connector is not None
        counts: dict[str, int] = {}
        reasons: list[str] = []
        total_latency = 0
        for timeframe, const_name in TIMEFRAMES.items():
            mt5_timeframe = getattr(self.connector.mt5, const_name, timeframe)
            rates, latency, error = measure_latency_ms(lambda tf=mt5_timeframe: self.connector.mt5.copy_rates_from_pos(broker_symbol, tf, 0, self.bars))
            total_latency += latency
            count = 0 if rates is None else len(rates)
            counts[timeframe] = count
            if error:
                reasons.append(f"{timeframe} read error: {error}")
            elif count <= 0:
                reasons.append(f"{timeframe} rates unavailable")
        return counts, total_latency, reasons

    def _not_ready(self, canonical_symbol: str, reason: str, *, broker_symbol: str | None = None) -> dict[str, Any]:
        return {
            "canonical_symbol": canonical_symbol,
            "broker_symbol": broker_symbol or canonical_symbol,
            "symbol_visible": False,
            "trade_mode": "",
            "trade_allowed": False,
            "bid": 0.0,
            "ask": 0.0,
            "spread_points": 0.0,
            "point": 0.0,
            "digits": 0,
            "tick_value": 0.0,
            "tick_size": 0.0,
            "trade_contract_size": 0.0,
            "volume_min": 0.0,
            "volume_max": 0.0,
            "volume_step": 0.0,
            "stops_level_points": -1,
            "freeze_level_points": -1,
            "filling_mode": "",
            "tick_time_utc": None,
            "tick_age_seconds": None,
            "mt5_last_error": None,
            "market_is_probably_closed": False,
            "rates_available_m5": False,
            "rates_available_m15": False,
            "rates_available_h1": False,
            "bars_count_m5": 0,
            "bars_count_m15": 0,
            "bars_count_h1": 0,
            "read_latency_ms_tick": 0,
            "read_latency_ms_rates": 0,
            "status": "NOT_READY",
            "reasons": (reason,),
            "readiness_score": 0.0,
            "execution_attempted": False,
            "order_send_called": False,
        }

    def _summary(self, symbols: list[dict[str, Any]], *, mt5_connected: bool) -> dict[str, Any]:
        return {
            "mode": "broker-quality",
            "mt5_connected": mt5_connected,
            "symbols_checked": len(symbols),
            "ready": sum(1 for item in symbols if item["status"] == "EXECUTION_READY_SHADOW_ONLY"),
            "watchlist": sum(1 for item in symbols if item["status"] == "WATCHLIST"),
            "not_ready": sum(1 for item in symbols if item["status"] == "NOT_READY"),
            "symbols": symbols,
            "classification": "EXECUTION_READY_SHADOW_ONLY" if symbols and all(item["status"] == "EXECUTION_READY_SHADOW_ONLY" for item in symbols) else "WATCHLIST" if any(item["status"] != "NOT_READY" for item in symbols) else "NOT_READY",
            "execution_attempted": False,
            "order_send_called": False,
            "reports_created": [],
        }

    def _audit(self, event_type: str, severity: Severity, payload: dict[str, Any], *, symbol: str | None = None) -> None:
        event = Event.create(
            run_id=self.run_id,
            environment=Environment.DEMO,
            severity=severity,
            module="broker_quality",
            event_type=event_type,
            message=event_type.lower(),
            correlation_id=f"{self.run_id}:{event_type}:{symbol or ''}",
            symbol=symbol,
            payload={**payload, "execution_attempted": False, "order_send_called": False},
        )
        if self.audit_logger is not None:
            self.audit_logger.append_event(event)
        if self.database is not None:
            self.database.insert_event(event)


def run_broker_quality(
    *,
    config: BotConfig,
    symbols: Iterable[str],
    log_dir: str | Path,
    database: TelemetryDatabase,
    report_dir: str | Path,
    mt5_client: Any | None = None,
    bars: int = 260,
) -> dict[str, Any]:
    probe = BrokerQualityProbe(
        config=config,
        symbols=symbols,
        audit_logger=JsonlAuditLogger(log_dir, max_file_mb=config.max_jsonl_file_mb),
        database=database,
        mt5_client=mt5_client,
        bars=bars,
    )
    summary = probe.run()
    reports = write_broker_quality_report(summary, report_dir)
    summary["reports_created"] = list(reports.values())
    return summary
