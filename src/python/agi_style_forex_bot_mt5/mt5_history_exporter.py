"""Read-only MT5 historical CSV exporter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .config import BotConfig
from .contracts import Environment, Event, Severity
from .execution import MT5Connector
from .mt5_data_bot import DEFAULT_FOREX_SYMBOLS
from .telemetry import JsonlAuditLogger, TelemetryDatabase


@dataclass(frozen=True)
class ExportHistorySummary:
    """Summary printed by `--mode export-history`."""

    mode: str
    mt5_connected: bool
    symbols_requested: int
    files_created: int
    rows_exported: int
    execution_attempted: bool = False


class MT5HistoryExporter:
    """Export MT5 bars to local CSV without signals or orders."""

    def __init__(
        self,
        *,
        config: BotConfig | None = None,
        symbols: Iterable[str] = DEFAULT_FOREX_SYMBOLS,
        timeframes: Iterable[str] = ("M5", "M15", "H1"),
        bars: int = 50_000,
        output_dir: str | Path = "data/historical",
        audit_logger: JsonlAuditLogger | None = None,
        database: TelemetryDatabase | None = None,
        mt5_client: Any | None = None,
    ) -> None:
        self.config = config or BotConfig()
        self.config.validate_safety()
        self.symbols = tuple(symbol.strip().upper() for symbol in symbols if symbol.strip())
        self.timeframes = tuple(timeframe.strip().upper() for timeframe in timeframes if timeframe.strip())
        self.bars = max(1, int(bars))
        self.output_dir = Path(output_dir)
        self.audit_logger = audit_logger
        self.database = database
        self.connector = MT5Connector(config=self.config, mt5_client=mt5_client)

    def run(self) -> ExportHistorySummary:
        """Export configured symbols/timeframes to CSV files."""

        initialize = getattr(self.connector.mt5, "initialize", None)
        if callable(initialize) and initialize() is not True:
            self._audit("MT5_CONNECTION_FAILED", Severity.CRITICAL, {"last_error": self.connector.last_error_payload()})
            return ExportHistorySummary("export-history", False, len(self.symbols), 0, 0, False)
        self._audit("MT5_CONNECTED", Severity.INFO, {"mode": "export-history", "execution_attempted": False})
        self.output_dir.mkdir(parents=True, exist_ok=True)
        files_created = 0
        rows_exported = 0
        for canonical_symbol in self.symbols:
            resolution_check, resolution = self.connector.resolve_symbol(canonical_symbol)
            if not resolution_check.accepted or resolution is None:
                self._audit(
                    "EXPORT_SYMBOL_REJECTED",
                    Severity.WARNING,
                    {"canonical_symbol": canonical_symbol, **resolution_check.payload},
                    symbol=canonical_symbol,
                )
                continue
            for timeframe in self.timeframes:
                mt5_timeframe = getattr(self.connector.mt5, f"TIMEFRAME_{timeframe}", timeframe)
                raw = self.connector.mt5.copy_rates_from_pos(
                    resolution.broker_symbol,
                    mt5_timeframe,
                    0,
                    self.bars,
                )
                if raw is None or len(raw) == 0:
                    self._audit(
                        "EXPORT_RATES_EMPTY",
                        Severity.WARNING,
                        {
                            "canonical_symbol": canonical_symbol,
                            "broker_symbol": resolution.broker_symbol,
                            "timeframe": timeframe,
                            "last_error": self.connector.last_error_payload(),
                        },
                        symbol=canonical_symbol,
                    )
                    continue
                frame = pd.DataFrame(raw)
                if "time" in frame.columns:
                    timestamp_utc = pd.to_datetime(frame["time"], unit="s", utc=True)
                    frame["timestamp_utc"] = timestamp_utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    frame["time"] = frame["timestamp_utc"]
                output_path = self.output_dir / f"{canonical_symbol}_{timeframe}.csv"
                frame.to_csv(output_path, index=False)
                files_created += 1
                rows_exported += len(frame)
                self._audit(
                    "HISTORY_EXPORTED",
                    Severity.INFO,
                    {
                        "canonical_symbol": canonical_symbol,
                        "broker_symbol": resolution.broker_symbol,
                        "timeframe": timeframe,
                        "rows": len(frame),
                        "output_path": str(output_path),
                        "execution_attempted": False,
                    },
                    symbol=canonical_symbol,
                )
        return ExportHistorySummary("export-history", True, len(self.symbols), files_created, rows_exported, False)

    def _audit(
        self,
        event_type: str,
        severity: Severity,
        payload: dict[str, Any],
        *,
        symbol: str | None = None,
    ) -> None:
        if self.audit_logger is None and self.database is None:
            return
        event = Event.create(
            run_id="export_history",
            environment=Environment.DEMO,
            severity=severity,
            module="mt5_export",
            event_type=event_type,
            message=event_type.lower(),
            correlation_id=f"export_history:{symbol or 'run'}:{event_type}",
            symbol=symbol,
            payload=payload,
        )
        if self.audit_logger is not None:
            self.audit_logger.append_event(event)
        if self.database is not None:
            self.database.insert_event(event)


def export_summary_to_json(summary: ExportHistorySummary) -> str:
    """Serialize export summary."""

    import json

    payload = asdict(summary) if is_dataclass(summary) else vars(summary)
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)
