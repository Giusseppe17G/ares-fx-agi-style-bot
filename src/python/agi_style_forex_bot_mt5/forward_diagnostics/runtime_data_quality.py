"""Read-only runtime MT5 data quality probes for forward diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.execution import MT5Connector


TIMEFRAMES: tuple[str, ...] = ("M5", "M15", "H1")


def probe_runtime_data_quality(
    *,
    config: BotConfig,
    connector: MT5Connector,
    symbols: Iterable[str],
    bars: int = 260,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return per-symbol runtime readiness plus raw rate arrays for feature probes."""

    rows: list[dict[str, Any]] = []
    rates_by_symbol: dict[str, dict[str, Any]] = {}
    for canonical in [symbol.strip().upper() for symbol in symbols if symbol.strip()]:
        now = datetime.now(timezone.utc)
        resolution_check, resolution = connector.resolve_symbol(canonical)
        if not resolution_check.accepted or resolution is None:
            rows.append(_row(canonical, canonical, "LIVE_SYMBOL_NOT_READY", resolution_check.reason))
            continue
        broker_symbol = resolution.broker_symbol
        check, snapshot = connector.ensure_symbol_snapshot(
            broker_symbol,
            canonical_symbol=resolution.canonical_symbol,
            now_utc=now,
            source="forward-signal-diagnose",
        )
        rates: dict[str, Any] = {}
        counts: dict[str, int] = {}
        blockers: list[str] = []
        last_candle: dict[str, str | None] = {}
        for timeframe in TIMEFRAMES:
            mt5_timeframe = getattr(connector.mt5, f"TIMEFRAME_{timeframe}", timeframe)
            raw = connector.mt5.copy_rates_from_pos(broker_symbol, mt5_timeframe, 0, max(1, int(bars)))
            if raw is None or len(raw) == 0:
                raw = _copy_rates_range_fallback(connector, broker_symbol, mt5_timeframe, max(1, int(bars)))
            count = 0 if raw is None else len(raw)
            rates[timeframe] = raw
            counts[timeframe] = count
            if count <= 0:
                blockers.append(f"LIVE_{timeframe}_EMPTY")
                last_candle[timeframe] = None
            else:
                last_candle[timeframe] = _last_candle_timestamp(raw)
                if count < 220:
                    blockers.append("LIVE_INSUFFICIENT_BARS")
        if not check.accepted:
            reason = _market_data_blocker(check.code, check.payload)
            blockers.append(reason)
        if snapshot is not None and snapshot.spread_points > config.max_spread_points_default:
            blockers.append("LIVE_SPREAD_TOO_HIGH")
        status = "READY" if snapshot is not None and not blockers else "NOT_READY"
        rows.append(
            {
                "symbol": canonical,
                "canonical_symbol": resolution.canonical_symbol,
                "broker_symbol": broker_symbol,
                "status": status,
                "blockers": tuple(dict.fromkeys(blockers)),
                "bid": check.payload.get("bid"),
                "ask": check.payload.get("ask"),
                "spread_points": check.payload.get("spread_points"),
                "tick_time_status": check.payload.get("tick_time_status"),
                "timestamp_normalized": check.payload.get("timestamp_normalized", False),
                "broker_time_offset_seconds": check.payload.get("broker_time_offset_seconds", 0),
                "tick_age_seconds_normalized": check.payload.get("tick_age_seconds_normalized"),
                "bars_m5": counts.get("M5", 0),
                "bars_m15": counts.get("M15", 0),
                "bars_h1": counts.get("H1", 0),
                "last_candle_m5": last_candle.get("M5"),
                "last_candle_m15": last_candle.get("M15"),
                "last_candle_h1": last_candle.get("H1"),
                "rates_closed_or_forming": "UNKNOWN",
                "reject_code": check.code if not check.accepted else "",
                "reject_reason": check.reason if not check.accepted else "",
                "execution_attempted": False,
            }
        )
        if snapshot is not None and not any(str(item).startswith("LIVE_") and str(item).endswith("_EMPTY") for item in blockers):
            rates_by_symbol[canonical] = {"broker_symbol": broker_symbol, "snapshot": snapshot, "rates": rates}
    return rows, rates_by_symbol


def _copy_rates_range_fallback(connector: MT5Connector, broker_symbol: str, mt5_timeframe: Any, bars: int) -> Any:
    copy_rates_range = getattr(connector.mt5, "copy_rates_range", None)
    if not callable(copy_rates_range):
        return None
    now = datetime.now(timezone.utc)
    return copy_rates_range(broker_symbol, mt5_timeframe, now, now)


def _last_candle_timestamp(raw: Any) -> str | None:
    try:
        item = raw[-1]
        value = item["time"] if isinstance(item, dict) else getattr(item, "time", None)
        if value is None:
            return None
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except Exception:
        return None


def _market_data_blocker(code: str, payload: dict[str, Any]) -> str:
    status = str(payload.get("tick_time_status") or "")
    if code == "MARKET_CLOSED_OR_NO_TICKS":
        return "LIVE_TICK_STALE"
    if status == "INVALID_TIMESTAMP":
        return "LIVE_TIMESTAMP_INVALID"
    if status in {"STALE", "NORMALIZED_STALE"}:
        return "LIVE_TICK_STALE"
    if "tick" in str(payload).lower():
        return "LIVE_TICK_MISSING"
    return "LIVE_SYMBOL_NOT_READY"


def _row(symbol: str, broker_symbol: str, blocker: str, reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "canonical_symbol": symbol,
        "broker_symbol": broker_symbol,
        "status": "NOT_READY",
        "blockers": (blocker,),
        "reject_code": blocker,
        "reject_reason": reason,
        "execution_attempted": False,
    }
