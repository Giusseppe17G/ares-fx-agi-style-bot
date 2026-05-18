"""Single MetaTrader 5 adapter used by Python execution code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Mapping

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import (
    Direction,
    EntryType,
    ExecutionRequest,
    ExecutionResult,
    MarketSnapshot,
    utc_now,
)
from agi_style_forex_bot_mt5.execution.mt5_time_normalizer import (
    build_environment_diagnostics,
    normalize_tick_time,
    persist_broker_time_offset,
)


RETCODE_DONE = 10009
RETCODE_DONE_PARTIAL = 10010
RETCODE_PLACED = 10008
RETCODE_REQUOTE = 10004
RETCODE_PRICE_CHANGED = 10020
RETCODE_PRICE_OFF = 10021
RETCODE_INVALID_STOPS = 10016
RETCODE_INVALID_VOLUME = 10014
RETCODE_INVALID_FILL = 10030
RETCODE_MARKET_CLOSED = 10018
RETCODE_TRADE_DISABLED = 10017
RETCODE_NO_MONEY = 10019
RETCODE_TOO_MANY_REQUESTS = 10024

SUCCESS_MARKET_RETCODES = {RETCODE_DONE}
SUCCESS_PENDING_RETCODES = {RETCODE_PLACED}
RECOVERABLE_RETCODES = {
    RETCODE_REQUOTE,
    RETCODE_PRICE_CHANGED,
    RETCODE_PRICE_OFF,
    RETCODE_TOO_MANY_REQUESTS,
}

RETCODE_DESCRIPTIONS = {
    0: "NOT_SENT",
    RETCODE_DONE: "TRADE_RETCODE_DONE",
    RETCODE_DONE_PARTIAL: "TRADE_RETCODE_DONE_PARTIAL",
    RETCODE_PLACED: "TRADE_RETCODE_PLACED",
    RETCODE_REQUOTE: "TRADE_RETCODE_REQUOTE",
    RETCODE_PRICE_CHANGED: "TRADE_RETCODE_PRICE_CHANGED",
    RETCODE_PRICE_OFF: "TRADE_RETCODE_PRICE_OFF",
    RETCODE_INVALID_STOPS: "TRADE_RETCODE_INVALID_STOPS",
    RETCODE_INVALID_VOLUME: "TRADE_RETCODE_INVALID_VOLUME",
    RETCODE_INVALID_FILL: "TRADE_RETCODE_INVALID_FILL",
    RETCODE_MARKET_CLOSED: "TRADE_RETCODE_MARKET_CLOSED",
    RETCODE_TRADE_DISABLED: "TRADE_RETCODE_TRADE_DISABLED",
    RETCODE_NO_MONEY: "TRADE_RETCODE_NO_MONEY",
    RETCODE_TOO_MANY_REQUESTS: "TRADE_RETCODE_TOO_MANY_REQUESTS",
}


@dataclass(frozen=True)
class AdapterCheck:
    """Validation result produced by the MT5 adapter."""

    accepted: bool
    code: str
    reason: str
    payload: dict[str, Any]

    @staticmethod
    def ok(reason: str = "OK", **payload: Any) -> "AdapterCheck":
        """Create an accepted check."""

        return AdapterCheck(True, "OK", reason, payload)

    @staticmethod
    def reject(code: str, reason: str, **payload: Any) -> "AdapterCheck":
        """Create a rejected check."""

        return AdapterCheck(False, code, reason, payload)


@dataclass(frozen=True)
class SymbolResolution:
    """Canonical/broker symbol mapping for broker-specific suffixes."""

    canonical_symbol: str
    broker_symbol: str


@dataclass(frozen=True)
class TickFreshness:
    """UTC-normalized tick time diagnostics."""

    tick_time_raw: int | float | None
    tick_time_msc_raw: int | float | None
    tick_time_utc: datetime | None
    tick_time_msc_utc: datetime | None
    selected_time_utc: datetime | None
    selected_source: str
    tick_age_seconds: float | None
    tick_age_seconds_from_time: float | None
    tick_age_seconds_from_time_msc: float | None
    now_utc: datetime
    tick_time_utc_raw: datetime | None = None
    normalized_tick_utc: datetime | None = None
    timestamp_normalized: bool = False
    broker_time_offset_seconds: int = 0
    tick_age_seconds_raw: float | None = None
    tick_age_seconds_normalized: float | None = None
    tick_time_status: str = ""
    normalization_reason: str = ""
    reject_code: str | None = None
    reject_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Return JSON-safe tick diagnostics for audit events."""

        return {
            "tick_time_raw": self.tick_time_raw,
            "tick_time_msc_raw": self.tick_time_msc_raw,
            "tick_time_utc": self.tick_time_utc.isoformat() if self.tick_time_utc else None,
            "tick_time_msc_utc": self.tick_time_msc_utc.isoformat() if self.tick_time_msc_utc else None,
            "tick_time_utc_raw": self.tick_time_utc_raw.isoformat() if self.tick_time_utc_raw else None,
            "normalized_tick_utc": self.normalized_tick_utc.isoformat() if self.normalized_tick_utc else None,
            "selected_tick_time_source": self.selected_source,
            "selected_tick_time_utc": self.selected_time_utc.isoformat() if self.selected_time_utc else None,
            "tick_age_seconds": self.tick_age_seconds,
            "tick_age_seconds_from_time": self.tick_age_seconds_from_time,
            "tick_age_seconds_from_time_msc": self.tick_age_seconds_from_time_msc,
            "timestamp_normalized": self.timestamp_normalized,
            "broker_time_offset_seconds": self.broker_time_offset_seconds,
            "tick_age_seconds_raw": self.tick_age_seconds_raw,
            "tick_age_seconds_normalized": self.tick_age_seconds_normalized,
            "tick_time_status": self.tick_time_status,
            "normalization_reason": self.normalization_reason,
            "now_utc": self.now_utc.isoformat(),
        }


def is_market_probably_closed(now_utc: datetime, symbol: str) -> bool:
    """Return true during common Forex weekend closure windows."""

    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)
    symbol_text = "".join(ch for ch in symbol.upper() if ch.isalpha())
    is_forex_like = len(symbol_text) >= 6 and symbol_text[:3].isalpha() and symbol_text[3:6].isalpha()
    if not is_forex_like:
        return False
    weekday = now_utc.weekday()
    hour = now_utc.hour
    if weekday == 5:
        return True
    if weekday == 6 and hour < 22:
        return True
    if weekday == 4 and hour >= 22:
        return True
    return False


class MT5Connector:
    """Encapsulate all calls to the MetaTrader5 Python module."""

    def __init__(self, *, config: BotConfig, mt5_client: Any | None = None) -> None:
        self.config = config
        self.mt5 = mt5_client if mt5_client is not None else self._import_mt5()

    def _import_mt5(self) -> Any:
        try:
            import MetaTrader5 as mt5  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("MetaTrader5 package is not installed") from exc
        return mt5

    def const(self, name: str, fallback: int) -> int:
        """Return an MT5 constant with a deterministic fallback for tests."""

        return int(getattr(self.mt5, name, fallback))

    def last_error_code(self) -> int:
        """Return the current MT5 last error code, if available."""

        last_error = getattr(self.mt5, "last_error", None)
        if not callable(last_error):
            return 0
        value = last_error()
        if isinstance(value, tuple) and value:
            return int(value[0])
        if isinstance(value, int):
            return value
        return 0

    def last_error_payload(self) -> Any:
        """Return the raw MT5 last_error payload for diagnostics."""

        last_error = getattr(self.mt5, "last_error", None)
        if not callable(last_error):
            return 0
        value = last_error()
        if isinstance(value, tuple):
            return list(value)
        return value

    def retcode_description(self, retcode: int) -> str:
        """Return human-readable retcode text."""

        return RETCODE_DESCRIPTIONS.get(int(retcode), f"TRADE_RETCODE_{retcode}")

    def is_recoverable_retcode(self, retcode: int) -> bool:
        """Return true when a retry is allowed after recapturing market data."""

        return int(retcode) in RECOVERABLE_RETCODES

    def is_success_retcode(self, retcode: int, order_type: EntryType) -> bool:
        """Return true only for retcodes accepted by project policy."""

        retcode = int(retcode)
        if order_type == EntryType.MARKET:
            if retcode in SUCCESS_MARKET_RETCODES:
                return True
            return retcode == RETCODE_DONE_PARTIAL and self.config.allow_partial_fill
        return retcode in SUCCESS_PENDING_RETCODES

    def validate_account_for_trading(self) -> AdapterCheck:
        """Validate terminal/account permissions and demo-only policy."""

        terminal = self.mt5.terminal_info()
        if terminal is None:
            return AdapterCheck.reject(
                "TERMINAL_TRADE_DISABLED",
                "terminal information unavailable",
                last_error=self.last_error_code(),
            )
        if getattr(terminal, "connected", True) is not True:
            return AdapterCheck.reject("TERMINAL_TRADE_DISABLED", "terminal disconnected")
        if getattr(terminal, "trade_allowed", True) is not True:
            return AdapterCheck.reject(
                "TERMINAL_TRADE_DISABLED",
                "algorithmic trading is disabled in terminal",
            )

        account = self.mt5.account_info()
        if account is None:
            return AdapterCheck.reject(
                "ACCOUNT_TYPE_UNKNOWN",
                "account information unavailable",
                last_error=self.last_error_code(),
            )
        login = getattr(account, "login", None)
        trade_mode = getattr(account, "trade_mode", None)
        if login is None or trade_mode is None:
            return AdapterCheck.reject(
                "ACCOUNT_TYPE_UNKNOWN",
                "account login or trade mode unavailable",
            )
        if getattr(account, "trade_allowed", True) is not True:
            return AdapterCheck.reject(
                "ACCOUNT_TRADE_DISABLED",
                "account trading is disabled",
                login=login,
            )

        is_demo = self._is_demo_trade_mode(trade_mode)
        if self.config.demo_only and not is_demo:
            return AdapterCheck.reject(
                "DEMO_ONLY_REAL_ACCOUNT",
                "DEMO_ONLY blocks non-demo accounts",
                login=login,
                trade_mode=trade_mode,
            )
        if not is_demo:
            if not self.config.live_trading_approved:
                return AdapterCheck.reject(
                    "LIVE_TRADING_NOT_APPROVED",
                    "live trading is not approved",
                    login=login,
                    trade_mode=trade_mode,
                )
            if int(login) not in self.config.allowed_account_logins:
                return AdapterCheck.reject(
                    "ACCOUNT_NOT_WHITELISTED",
                    "account is not whitelisted for live trading",
                    login=login,
                    trade_mode=trade_mode,
                )

        return AdapterCheck.ok(
            "account accepted",
            login=login,
            trade_mode=trade_mode,
            is_demo=is_demo,
            margin_mode=getattr(account, "margin_mode", ""),
        )

    def _is_demo_trade_mode(self, trade_mode: Any) -> bool:
        demo_constant = getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        if demo_constant is not None and trade_mode == demo_constant:
            return True
        if isinstance(trade_mode, str):
            return "demo" in trade_mode.lower()
        return int(trade_mode) == 0 if isinstance(trade_mode, int) else False

    def resolve_symbol(self, canonical_symbol: str) -> tuple[AdapterCheck, SymbolResolution | None]:
        """Resolve a canonical symbol to the broker symbol exposed by MT5."""

        canonical = canonical_symbol.strip().upper()
        if not canonical:
            return AdapterCheck.reject("SYMBOL_NOT_ALLOWED", "canonical symbol is empty"), None
        direct_info = self.mt5.symbol_info(canonical)
        if direct_info is not None:
            name = str(getattr(direct_info, "name", canonical) or canonical)
            return AdapterCheck.ok(
                "symbol resolved",
                canonical_symbol=canonical,
                broker_symbol=name,
                match_type="exact",
            ), SymbolResolution(canonical_symbol=canonical, broker_symbol=name)

        candidates = self._symbol_candidates(canonical)
        candidate_lookup = {candidate.upper() for candidate in candidates}
        symbols_get = getattr(self.mt5, "symbols_get", None)
        if callable(symbols_get):
            try:
                found = symbols_get(f"*{canonical}*")
            except TypeError:
                found = symbols_get()
            except Exception:
                found = ()
            for item in found or ():
                name = str(getattr(item, "name", "") or "")
                if not name:
                    continue
                if name.upper() in candidate_lookup:
                    return AdapterCheck.ok(
                        "symbol resolved",
                        canonical_symbol=canonical,
                        broker_symbol=name,
                        match_type="symbols_get",
                    ), SymbolResolution(canonical_symbol=canonical, broker_symbol=name)

        for candidate in candidates:
            if self.mt5.symbol_info(candidate) is not None:
                return AdapterCheck.ok(
                    "symbol resolved",
                    canonical_symbol=canonical,
                    broker_symbol=candidate,
                    match_type="candidate",
                ), SymbolResolution(canonical_symbol=canonical, broker_symbol=candidate)

        return AdapterCheck.reject(
            "SYMBOL_NOT_ALLOWED",
            "symbol information unavailable",
            canonical_symbol=canonical,
            broker_symbol=None,
            last_error=self.last_error_code(),
        ), None

    def _symbol_candidates(self, canonical_symbol: str) -> tuple[str, ...]:
        suffixes = ("", "m", ".r", ".raw", "pro", ".")
        return tuple(f"{canonical_symbol}{suffix}" for suffix in suffixes)

    def ensure_symbol_snapshot(
        self,
        symbol: str,
        *,
        canonical_symbol: str | None = None,
        now_utc: datetime | None = None,
        source: str = "mt5-data",
    ) -> tuple[AdapterCheck, MarketSnapshot | None]:
        """Select a symbol, validate fresh tick/properties, and return a snapshot."""

        canonical = (canonical_symbol or symbol).strip().upper()
        now = (now_utc or utc_now()).astimezone(timezone.utc)
        symbol_info = self.mt5.symbol_info(symbol)
        if symbol_info is None:
            return (
                AdapterCheck.reject(
                    "SYMBOL_NOT_ALLOWED",
                    "symbol information unavailable",
                    symbol=canonical,
                    canonical_symbol=canonical,
                    broker_symbol=symbol,
                    last_error=self.last_error_code(),
                ),
                None,
            )
        if getattr(symbol_info, "visible", True) is not True:
            selected = self.mt5.symbol_select(symbol, True)
            if selected is not True:
                return (
                    AdapterCheck.reject(
                        "SYMBOL_NOT_ALLOWED",
                        "symbol could not be selected",
                        symbol=canonical,
                        canonical_symbol=canonical,
                        broker_symbol=symbol,
                        last_error=self.last_error_code(),
                    ),
                    None,
                )
            symbol_info = self.mt5.symbol_info(symbol)
            if symbol_info is None:
                return (
                    AdapterCheck.reject(
                        "SYMBOL_NOT_ALLOWED",
                        "symbol information unavailable after selection",
                        symbol=canonical,
                        canonical_symbol=canonical,
                        broker_symbol=symbol,
                    ),
                    None,
                )

        if not self._symbol_trading_enabled(symbol_info):
            return (
                AdapterCheck.reject(
                    "SYMBOL_TRADE_DISABLED",
                    "symbol trading is disabled",
                    symbol=canonical,
                    canonical_symbol=canonical,
                    broker_symbol=symbol,
                ),
                None,
            )

        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            return (
                AdapterCheck.reject(
                    "MARKET_DATA_INVALID",
                    "tick unavailable",
                    symbol=canonical,
                    canonical_symbol=canonical,
                    broker_symbol=symbol,
                    last_error=self.last_error_code(),
                ),
                None,
            )
        bid = float(getattr(tick, "bid", 0.0))
        ask = float(getattr(tick, "ask", 0.0))
        point = float(getattr(symbol_info, "point", 0.0))
        if bid <= 0 or ask <= 0 or ask < bid or point <= 0:
            return (
                AdapterCheck.reject(
                    "MARKET_DATA_INVALID",
                    "tick prices or point are invalid",
                    symbol=canonical,
                    canonical_symbol=canonical,
                    broker_symbol=symbol,
                    bid=bid,
                    ask=ask,
                    point=point,
                ),
                None,
            )

        freshness = self.tick_freshness(tick, now_utc=now)
        tick_age = freshness.tick_age_seconds
        base_payload = {
            "symbol": canonical,
            "canonical_symbol": canonical,
            "broker_symbol": symbol,
            "bid": bid,
            "ask": ask,
            "spread_points": (ask - bid) / point,
            "mt5_last_error": self.last_error_payload(),
            "market_is_probably_closed": is_market_probably_closed(now, canonical),
            "max_tick_age_seconds": self.config.max_tick_age_seconds,
            **freshness.to_payload(),
            **self.environment_diagnostics(),
        }
        if freshness.selected_time_utc is None or tick_age is None:
            return (
                AdapterCheck.reject(
                    "MARKET_DATA_INVALID",
                    freshness.reject_reason or "tick timestamp is unavailable or invalid",
                    **base_payload,
                ),
                None,
            )
        fresh_statuses = {"FRESH", "NORMALIZED_FRESH"}
        if freshness.tick_time_status not in fresh_statuses or abs(tick_age) > self.config.max_tick_age_seconds:
            market_closed = is_market_probably_closed(now, canonical)
            reject_code = "MARKET_CLOSED_OR_NO_TICKS" if market_closed and freshness.tick_time_status != "INVALID_TIMESTAMP" else "MARKET_DATA_INVALID"
            reject_reason = freshness.reject_reason or (
                "market appears closed or symbol has no fresh ticks" if market_closed else "tick timestamp is stale or in the future"
            )
            return (
                AdapterCheck.reject(
                    reject_code,
                    reject_reason,
                    **base_payload,
                ),
                None,
            )
        if freshness.timestamp_normalized:
            path = self.persist_time_offset_hint(
                symbol=canonical,
                diagnostic=base_payload,
                source=source,
            )
            if path:
                base_payload["broker_time_offset_path"] = path

        snapshot = MarketSnapshot(
            symbol=canonical,
            timeframe="EXECUTION",
            timestamp_utc=freshness.selected_time_utc,
            bid=bid,
            ask=ask,
            spread_points=(ask - bid) / point,
            digits=int(getattr(symbol_info, "digits", 0)),
            point=point,
            tick_value=float(getattr(symbol_info, "trade_tick_value", 0.0)),
            tick_size=float(getattr(symbol_info, "trade_tick_size", 0.0)),
            volume_min=float(getattr(symbol_info, "volume_min", 0.0)),
            volume_max=float(getattr(symbol_info, "volume_max", 0.0)),
            volume_step=float(getattr(symbol_info, "volume_step", 0.0)),
            stops_level_points=int(getattr(symbol_info, "trade_stops_level", -1)),
            freeze_level_points=int(getattr(symbol_info, "trade_freeze_level", -1)),
        )
        try:
            snapshot.validate()
        except ValueError as exc:
            return (
                AdapterCheck.reject(
                    "MARKET_DATA_INVALID",
                    str(exc),
                    symbol=canonical,
                    canonical_symbol=canonical,
                    broker_symbol=symbol,
                ),
                None,
            )
        return (
            AdapterCheck.ok(
                "symbol snapshot accepted",
                **base_payload,
            ),
            snapshot,
        )

    def _tick_timestamp(self, tick: Any) -> datetime:
        freshness = self.tick_freshness(tick)
        if freshness.selected_time_utc is None:
            raise ValueError("tick timestamp is unavailable or invalid")
        return freshness.selected_time_utc

    def tick_freshness(self, tick: Any, *, now_utc: datetime | None = None) -> TickFreshness:
        """Calculate tick age in UTC, normalizing known broker-server offsets."""

        now = (now_utc or utc_now()).astimezone(timezone.utc)
        raw_time = getattr(tick, "time", None)
        raw_time_msc = getattr(tick, "time_msc", None)
        diagnostic = normalize_tick_time(raw_time, raw_time_msc, now, config=self.config)
        time_utc = self._from_iso(diagnostic.get("tick_time_utc"))
        time_msc_utc = self._from_iso(diagnostic.get("tick_time_msc_utc"))
        selected = self._from_iso(diagnostic.get("selected_tick_time_utc"))
        return TickFreshness(
            tick_time_raw=raw_time,
            tick_time_msc_raw=raw_time_msc,
            tick_time_utc=time_utc,
            tick_time_msc_utc=time_msc_utc,
            selected_time_utc=selected,
            selected_source=str(diagnostic.get("selected_tick_time_source") or "none"),
            tick_age_seconds=diagnostic.get("tick_age_seconds_normalized"),
            tick_age_seconds_from_time=diagnostic.get("tick_age_seconds_from_time"),
            tick_age_seconds_from_time_msc=diagnostic.get("tick_age_seconds_from_time_msc"),
            now_utc=now,
            tick_time_utc_raw=self._from_iso(diagnostic.get("tick_time_utc_raw")),
            normalized_tick_utc=self._from_iso(diagnostic.get("normalized_tick_utc")),
            timestamp_normalized=bool(diagnostic.get("timestamp_normalized")),
            broker_time_offset_seconds=int(diagnostic.get("broker_time_offset_seconds") or 0),
            tick_age_seconds_raw=diagnostic.get("tick_age_seconds_raw"),
            tick_age_seconds_normalized=diagnostic.get("tick_age_seconds_normalized"),
            tick_time_status=str(diagnostic.get("tick_time_status") or ""),
            normalization_reason=str(diagnostic.get("normalization_reason") or ""),
            reject_code=diagnostic.get("reject_code"),
            reject_reason=diagnostic.get("reject_reason"),
        )

    def environment_diagnostics(self) -> dict[str, Any]:
        terminal_info = getattr(self.mt5, "terminal_info", None)
        terminal_available = None
        if callable(terminal_info):
            try:
                terminal_available = terminal_info() is not None
            except Exception:
                terminal_available = False
        return build_environment_diagnostics(mt5_terminal_available=terminal_available)

    def persist_time_offset_hint(self, *, symbol: str, diagnostic: Mapping[str, Any], source: str) -> str | None:
        account_info = getattr(self.mt5, "account_info", None)
        account = None
        if callable(account_info):
            try:
                account = account_info()
            except Exception:
                account = None
        return persist_broker_time_offset(diagnostic=diagnostic, symbol=symbol, source=source, account_info=account)

    def _from_iso(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _unix_timestamp(self, raw_value: Any, *, divisor: float) -> datetime | None:
        if raw_value in (None, ""):
            return None
        try:
            value = float(raw_value) / divisor
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        if value < 946684800 or value > 4102444800:
            return None
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    def _symbol_trading_enabled(self, symbol_info: Any) -> bool:
        trade_mode = getattr(symbol_info, "trade_mode", None)
        disabled = getattr(self.mt5, "SYMBOL_TRADE_MODE_DISABLED", None)
        if disabled is not None and trade_mode == disabled:
            return False
        if isinstance(trade_mode, str):
            return trade_mode.upper() not in {"DISABLED", "SYMBOL_TRADE_MODE_DISABLED"}
        return True

    def validate_volume(self, request: ExecutionRequest, snapshot: MarketSnapshot) -> AdapterCheck:
        """Validate lot against symbol min/max/step without rounding up."""

        lot = request.lot
        if lot < snapshot.volume_min or lot > snapshot.volume_max:
            return AdapterCheck.reject(
                "INVALID_LOT",
                "lot outside symbol volume limits",
                lot=lot,
                volume_min=snapshot.volume_min,
                volume_max=snapshot.volume_max,
            )
        steps = round((lot - snapshot.volume_min) / snapshot.volume_step)
        aligned = abs(snapshot.volume_min + steps * snapshot.volume_step - lot) < 1e-9
        if not aligned:
            return AdapterCheck.reject(
                "INVALID_LOT",
                "lot is not aligned to symbol volume step",
                lot=lot,
                volume_step=snapshot.volume_step,
            )
        return AdapterCheck.ok("volume accepted", lot=lot)

    def validate_stops(self, request: ExecutionRequest, snapshot: MarketSnapshot) -> AdapterCheck:
        """Validate SL/TP direction plus stops and freeze levels."""

        if snapshot.stops_level_points < 0 or snapshot.freeze_level_points < 0:
            return AdapterCheck.reject(
                "EXECUTION_CONSTRAINT",
                "stops or freeze levels unavailable",
            )
        min_distance = snapshot.stops_level_points * snapshot.point
        freeze_distance = snapshot.freeze_level_points * snapshot.point
        bid = snapshot.bid
        ask = snapshot.ask

        if request.order_type == EntryType.MARKET:
            if request.direction == Direction.BUY:
                if request.sl_price > bid - min_distance:
                    return AdapterCheck.reject("EXECUTION_CONSTRAINT", "BUY SL violates stops level")
                if request.tp_price < bid + min_distance:
                    return AdapterCheck.reject("EXECUTION_CONSTRAINT", "BUY TP violates stops level")
                if bid - request.sl_price <= freeze_distance or request.tp_price - bid <= freeze_distance:
                    return AdapterCheck.reject("EXECUTION_CONSTRAINT", "BUY SL/TP inside freeze level")
            else:
                if request.sl_price < ask + min_distance:
                    return AdapterCheck.reject("EXECUTION_CONSTRAINT", "SELL SL violates stops level")
                if request.tp_price > ask - min_distance:
                    return AdapterCheck.reject("EXECUTION_CONSTRAINT", "SELL TP violates stops level")
                if request.sl_price - ask <= freeze_distance or ask - request.tp_price <= freeze_distance:
                    return AdapterCheck.reject("EXECUTION_CONSTRAINT", "SELL SL/TP inside freeze level")
            return AdapterCheck.ok("stops accepted")

        if request.entry_price is None or request.entry_price <= 0:
            return AdapterCheck.reject(
                "EXECUTION_CONSTRAINT",
                "pending orders require entry_price",
            )
        entry = request.entry_price
        if request.direction == Direction.BUY and not (request.sl_price < entry < request.tp_price):
            return AdapterCheck.reject("EXECUTION_CONSTRAINT", "BUY pending SL/TP invalid")
        if request.direction == Direction.SELL and not (request.tp_price < entry < request.sl_price):
            return AdapterCheck.reject("EXECUTION_CONSTRAINT", "SELL pending SL/TP invalid")
        if abs(entry - bid) <= freeze_distance or abs(entry - ask) <= freeze_distance:
            return AdapterCheck.reject("EXECUTION_CONSTRAINT", "pending price inside freeze level")
        if min(abs(entry - request.sl_price), abs(entry - request.tp_price)) < min_distance:
            return AdapterCheck.reject("EXECUTION_CONSTRAINT", "pending SL/TP violates stops level")
        return AdapterCheck.ok("pending stops accepted")

    def select_filling_mode(self, symbol: str) -> tuple[AdapterCheck, int | None, str]:
        """Select a supported filling mode for explicit request construction."""

        symbol_info = self.mt5.symbol_info(symbol)
        if symbol_info is None:
            return AdapterCheck.reject("INVALID_FILLING_MODE", "symbol unavailable"), None, ""
        raw_mode = getattr(symbol_info, "filling_mode", None)
        if raw_mode is None:
            return AdapterCheck.reject("INVALID_FILLING_MODE", "filling mode unavailable"), None, ""

        candidates = (
            ("ORDER_FILLING_FOK", self.const("ORDER_FILLING_FOK", 0)),
            ("ORDER_FILLING_IOC", self.const("ORDER_FILLING_IOC", 1)),
            ("ORDER_FILLING_RETURN", self.const("ORDER_FILLING_RETURN", 2)),
        )
        for name, value in candidates:
            if int(raw_mode) == value or int(raw_mode) & (1 << value):
                return AdapterCheck.ok("filling mode accepted", mode=name), value, name
        return (
            AdapterCheck.reject(
                "INVALID_FILLING_MODE",
                "no compatible filling mode",
                raw_mode=raw_mode,
            ),
            None,
            "",
        )

    def build_trade_request(
        self,
        request: ExecutionRequest,
        snapshot: MarketSnapshot,
        filling_mode: int,
    ) -> dict[str, Any]:
        """Build a safe MqlTradeRequest-equivalent dictionary."""

        request.validate()
        order_type = self._order_type(request)
        action = (
            self.const("TRADE_ACTION_DEAL", 1)
            if request.order_type == EntryType.MARKET
            else self.const("TRADE_ACTION_PENDING", 5)
        )
        price = request.entry_price
        if request.order_type == EntryType.MARKET:
            price = snapshot.ask if request.direction == Direction.BUY else snapshot.bid
        if price is None or price <= 0:
            raise ValueError("request price is required")
        comment = self._sanitize_comment(request.comment, request.signal_id)
        return {
            "action": action,
            "symbol": request.symbol,
            "volume": request.lot,
            "type": order_type,
            "price": round(price, snapshot.digits),
            "sl": round(request.sl_price, snapshot.digits),
            "tp": round(request.tp_price, snapshot.digits),
            "deviation": int(request.max_slippage_points),
            "magic": int(request.magic_number),
            "comment": comment,
            "type_time": self.const("ORDER_TIME_GTC", 0),
            "type_filling": filling_mode,
        }

    def _order_type(self, request: ExecutionRequest) -> int:
        if request.order_type == EntryType.MARKET:
            return self.const("ORDER_TYPE_BUY", 0) if request.direction == Direction.BUY else self.const("ORDER_TYPE_SELL", 1)
        if request.order_type == EntryType.LIMIT:
            return self.const("ORDER_TYPE_BUY_LIMIT", 2) if request.direction == Direction.BUY else self.const("ORDER_TYPE_SELL_LIMIT", 3)
        return self.const("ORDER_TYPE_BUY_STOP", 4) if request.direction == Direction.BUY else self.const("ORDER_TYPE_SELL_STOP", 5)

    def _sanitize_comment(self, comment: str, signal_id: str) -> str:
        base = "".join(ch for ch in comment if ch.isalnum() or ch in {"_", "-", ":"})[:12]
        suffix = "".join(ch for ch in signal_id if ch.isalnum() or ch in {"_", "-"})[:16]
        return f"{base or 'agi'}:{suffix}"[:31]

    def order_check(self, trade_request: dict[str, Any]) -> AdapterCheck:
        """Run MT5 order_check and normalize the result."""

        result = self.mt5.order_check(trade_request)
        if result is None:
            return AdapterCheck.reject(
                "EXECUTION_CONSTRAINT",
                "order_check returned no result",
                last_error=self.last_error_code(),
            )
        retcode = int(getattr(result, "retcode", 0))
        if retcode != RETCODE_DONE:
            return AdapterCheck.reject(
                self._retcode_to_reject_code(retcode),
                self.retcode_description(retcode),
                retcode=retcode,
                comment=getattr(result, "comment", ""),
            )
        return AdapterCheck.ok("order_check accepted", retcode=retcode)

    def order_send(
        self,
        *,
        execution_request: ExecutionRequest,
        trade_request: dict[str, Any],
        filling_mode_name: str,
    ) -> ExecutionResult:
        """Send the request once and convert the MT5 result to ExecutionResult."""

        started = perf_counter()
        result = self.mt5.order_send(trade_request)
        latency_ms = int((perf_counter() - started) * 1000)
        if result is None:
            return ExecutionResult(
                signal_id=execution_request.signal_id,
                sent=False,
                filled=False,
                retcode=0,
                retcode_description="ORDER_SEND_RETURNED_NONE",
                timestamp_utc=utc_now(),
                requested_lot=execution_request.lot,
                error_message="order_send returned no result",
                last_error=self.last_error_code(),
                execution_latency_ms=latency_ms,
                filling_mode_used=filling_mode_name,
            )

        retcode = int(getattr(result, "retcode", 0))
        filled = self.is_success_retcode(retcode, execution_request.order_type)
        fill_price = float(getattr(result, "price", 0.0) or 0.0)
        filled_lot = float(getattr(result, "volume", 0.0) or 0.0) if filled else 0.0
        return ExecutionResult(
            signal_id=execution_request.signal_id,
            sent=True,
            filled=filled,
            retcode=retcode,
            retcode_description=self.retcode_description(retcode),
            timestamp_utc=utc_now(),
            ticket=getattr(result, "order", None) or getattr(result, "deal", None),
            fill_price=fill_price,
            requested_lot=execution_request.lot,
            filled_lot=filled_lot,
            error_message="" if filled else getattr(result, "comment", ""),
            order_ticket=getattr(result, "order", None),
            deal_ticket=getattr(result, "deal", None),
            position_ticket=getattr(result, "position", None),
            request_id=getattr(result, "request_id", None),
            last_error=self.last_error_code(),
            server_comment=getattr(result, "comment", ""),
            execution_latency_ms=latency_ms,
            account_margin_mode=str(self._account_margin_mode()),
            filling_mode_used=filling_mode_name,
        )

    def _account_margin_mode(self) -> Any:
        account = self.mt5.account_info()
        return "" if account is None else getattr(account, "margin_mode", "")

    def _retcode_to_reject_code(self, retcode: int) -> str:
        if retcode == RETCODE_INVALID_STOPS:
            return "EXECUTION_CONSTRAINT"
        if retcode == RETCODE_INVALID_VOLUME:
            return "INVALID_LOT"
        if retcode == RETCODE_INVALID_FILL:
            return "INVALID_FILLING_MODE"
        if retcode == RETCODE_MARKET_CLOSED:
            return "MARKET_CLOSED"
        if retcode == RETCODE_TRADE_DISABLED:
            return "SYMBOL_TRADE_DISABLED"
        if retcode == RETCODE_NO_MONEY:
            return "EXECUTION_CONSTRAINT"
        return "EXECUTION_CONSTRAINT"
