"""Read-only broker swap terms, captured per symbol and failing closed per symbol.

Carry and swap costs were assumed until now (the daily study assumed a 75 bps
per year mark-up). This module records what the broker actually reports so
financing costs can be measured over time. It neither imports MetaTrader5 nor
starts, authenticates or queries a terminal account: the only client call is
``symbol_info`` on each explicitly mapped broker symbol, and only these
instrument fields are copied (everything else ``symbol_info`` returns, such as
quotes or volume limits, is ignored):

``swap_long``, ``swap_short``, ``swap_mode`` (raw integer plus the documented
``ENUM_SYMBOL_SWAP_MODE`` name), ``swap_rollover3days`` (raw integer plus the
``ENUM_DAY_OF_WEEK`` name), ``currency_base``, ``currency_profit``,
``currency_margin``, ``trade_contract_size``, ``point``, ``digits`` and the
current ``spread`` in points.

A symbol whose ``symbol_info`` is missing, raises, or carries a missing or
invalid field is recorded as ``UNAVAILABLE`` with a closed reason code (never
the client's own text, which may hold credentials or paths); the other symbols
are still captured and the snapshot status becomes ``PARTIAL`` (``UNAVAILABLE``
when nothing was captured). The payload carries the capture instant in UTC,
the declared ``MT5_SERVER_TIME`` convention, a ``swap_terms_hash`` that ignores
capture time and spread (it changes only when the recorded terms change), and
``payload_sha256``: the sha256 of the canonical JSON of every other field. The
hashes prove integrity, not authentic origin.

``annualised_swap_carry`` converts ``SWAP_MODE_POINTS`` terms into an
approximate annual percent of notional from the broker's own point and
contract size and a caller-supplied price, valued in USD like
``core.instruments.derive_tick_value``. Its output is labelled ``OBSERVED``:
no swap rate or mark-up is assumed. Every mode it cannot convert, a cross
without a USD leg, a weekend triple-swap day and an invalid price fail closed.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .core.instruments.registry import _unique_json_object, derive_tick_value
from .core.operational_state.errors import InstrumentError
from .core.safety import SafetyEnvelope
from .instrument_registry_builder import SymbolInfoClient, validate_symbol_map
from .utils.mt5_server_time import parse_server_time


SWAP_SNAPSHOT_SCHEMA_VERSION = "broker_swap_snapshot_v1"
SWAP_SNAPSHOT_SOURCE = "mt5:symbol_info"
SWAP_CARRY_SCHEMA_VERSION = "broker_swap_carry_v1"
_SOURCE = "broker_swap_snapshot"

CAPTURED = "CAPTURED"
PARTIAL = "PARTIAL"
UNAVAILABLE = "UNAVAILABLE"
OBSERVED = "OBSERVED"

# MQL5 ENUM_SYMBOL_SWAP_MODE, as exported by the MetaTrader5 Python package
# (SYMBOL_SWAP_MODE_<NAME>). Values outside this table are SWAP_MODE_UNKNOWN.
SWAP_MODE_NAMES: Mapping[int, str] = MappingProxyType({
    0: "DISABLED",  # no swaps
    1: "POINTS",  # swap_long/swap_short in points of the symbol price
    2: "CURRENCY_SYMBOL",  # money, in the symbol's base currency
    3: "CURRENCY_MARGIN",  # money, in the symbol's margin currency
    4: "CURRENCY_DEPOSIT",  # money, in the client's deposit currency
    5: "INTEREST_CURRENT",  # annual percent of the current instrument price
    6: "INTEREST_OPEN",  # annual percent of the position's open price
    7: "REOPEN_CURRENT",  # position reopened at the close price +/- points
    8: "REOPEN_BID",  # position reopened at the current Bid +/- points
})
SWAP_MODE_POINTS = 1

# MQL5 ENUM_DAY_OF_WEEK (DAY_OF_WEEK_<NAME>): the day the triple swap is charged.
DAY_OF_WEEK_NAMES: Mapping[int, str] = MappingProxyType({
    0: "SUNDAY", 1: "MONDAY", 2: "TUESDAY", 3: "WEDNESDAY", 4: "THURSDAY", 5: "FRIDAY", 6: "SATURDAY",
})
_WEEKDAYS = frozenset({1, 2, 3, 4, 5})

# symbol_info attribute -> snapshot field. Only these are ever read.
SYMBOL_INFO_FIELDS: Mapping[str, str] = MappingProxyType({
    "name": "broker_symbol",
    "swap_long": "swap_long",
    "swap_short": "swap_short",
    "swap_mode": "swap_mode",
    "swap_rollover3days": "swap_rollover3days",
    "currency_base": "currency_base",
    "currency_profit": "currency_profit",
    "currency_margin": "currency_margin",
    "trade_contract_size": "trade_contract_size",
    "point": "point",
    "digits": "digits",
    "spread": "spread_points",
})
_CAPTURED_KEYS = (
    "canonical_symbol", "broker_symbol", "status", "swap_long", "swap_short", "swap_mode", "swap_mode_name",
    "swap_rollover3days", "swap_rollover3days_name", "currency_base", "currency_profit", "currency_margin",
    "trade_contract_size", "point", "digits", "spread_points",
)
_UNAVAILABLE_KEYS = ("canonical_symbol", "broker_symbol", "status", "reason")
_PAYLOAD_KEYS = frozenset({
    "schema_version", "source", "captured_at_utc", "mt5_server_time", "status", "instrument_count",
    "captured_count", "unavailable_count", "symbols", "instruments", "enum_constants_checked",
    "account_data_read", "swap_terms_hash", "payload_sha256",
    "execution_attempted", "order_send_called", "order_check_called", "demo_only", "live_trading_approved",
})

# Closed set of per-symbol unavailability reasons; never free text.
UNAVAILABLE_REASONS = frozenset(
    {"SYMBOL_INFO_MISSING", "SYMBOL_INFO_FAILED", "BROKER_NAME_MISMATCH", "SWAP_MODE_UNKNOWN",
     "CURRENCY_MISMATCH", "POINT_DIGITS_MISMATCH"}
    | {f"FIELD_MISSING:{field}" for field in SYMBOL_INFO_FIELDS}
    | {f"FIELD_INVALID:{field}" for field in SYMBOL_INFO_FIELDS}
)

DAYS_PER_YEAR = 365  # one charge per calendar day on average: 5 rollovers, one of them triple
_CARRY_CURRENCY = "USD"
_MAX_DIGITS = 323  # beyond this 10**-digits is not a positive double
_MISSING = object()


class _Unavailable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------- capture


def check_mt5_enum_constants(client: Any) -> bool:
    """Compare the client's exported enum constants with the documented values.

    Constants are read statically (``inspect.getattr_static``), so a client's
    ``__getattr__`` is never invoked and no terminal call is made. Returns True
    when at least one constant was exposed and all exposed ones agree; raises
    ``InstrumentError`` when any disagrees, so a package with different numbers
    can never label swap terms with the wrong mode.
    """

    checked = 0
    for prefix, names in (("SYMBOL_SWAP_MODE_", SWAP_MODE_NAMES), ("DAY_OF_WEEK_", DAY_OF_WEEK_NAMES)):
        for code, name in names.items():
            value = inspect.getattr_static(client, prefix + name, _MISSING)
            if value is _MISSING:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or int(value) != code:
                raise InstrumentError(
                    "MetaTrader5 enum constants disagree with the documented ENUM_SYMBOL_SWAP_MODE/ENUM_DAY_OF_WEEK values",
                    source=_SOURCE, detail={"constant": prefix + name},
                )
            checked += 1
    return checked > 0


def _canonical_server_time(value: Any) -> str:
    try:
        canonical = parse_server_time(value)
    except ValueError:
        canonical = None
    if not isinstance(value, str) or canonical != value:
        raise InstrumentError("mt5_server_time must be a canonical MT5_SERVER_TIME value", source=_SOURCE)
    return value


def build_swap_snapshot(
    *,
    client: SymbolInfoClient,
    symbols: Mapping[str, str],
    captured_at_utc: datetime,
    mt5_server_time: str,
) -> dict[str, Any]:
    """Capture the swap terms of every mapped symbol; one bad symbol never hides the rest.

    Inputs are validated before any client call. The client's connection is
    owned by the caller. Symbols are read in canonical order, so the payload
    and its hashes do not depend on the map's order or the clock's time zone.
    """

    if not isinstance(captured_at_utc, datetime) or captured_at_utc.utcoffset() is None:
        raise InstrumentError("captured_at_utc must be a timezone-aware datetime", source=_SOURCE)
    server_time = _canonical_server_time(mt5_server_time)
    aliases = validate_symbol_map(symbols)
    enum_constants_checked = check_mt5_enum_constants(client)
    records: dict[str, dict[str, Any]] = {}
    for canonical, broker in sorted(aliases.items()):
        try:
            info = client.symbol_info(broker)
        except Exception:
            # The exception text may hold credentials, server names or paths.
            records[canonical] = _unavailable(canonical, broker, "SYMBOL_INFO_FAILED")
            continue
        records[canonical] = capture_swap_record(canonical, broker, info)
    return _assemble(records, captured_at_utc.astimezone(timezone.utc).isoformat(), server_time, enum_constants_checked)


def capture_swap_record(canonical: str, broker: str, info: Any) -> dict[str, Any]:
    """Map one ``symbol_info`` result onto a CAPTURED or UNAVAILABLE record."""

    if info is None:
        return _unavailable(canonical, broker, "SYMBOL_INFO_MISSING")
    try:
        return _captured(canonical, broker, info)
    except _Unavailable as unavailable:
        return _unavailable(canonical, broker, unavailable.reason)
    except Exception:
        # A property that raises is the client failing, not a missing field.
        return _unavailable(canonical, broker, "SYMBOL_INFO_FAILED")


def _unavailable(canonical: str, broker: str, reason: str) -> dict[str, Any]:
    return {"canonical_symbol": canonical, "broker_symbol": broker, "status": UNAVAILABLE, "reason": reason}


def _read(info: Any, name: str) -> Any:
    if isinstance(info, Mapping):
        return info[name] if name in info else _MISSING
    try:
        return getattr(info, name)
    except AttributeError:
        return _MISSING


def _captured(canonical: str, broker: str, info: Any) -> dict[str, Any]:
    raw = {name: _read(info, name) for name in SYMBOL_INFO_FIELDS}
    for name, value in raw.items():
        if value is _MISSING:
            raise _Unavailable(f"FIELD_MISSING:{name}")
    name = _text(raw["name"], "name")
    swap_long = _finite(raw["swap_long"], "swap_long")
    swap_short = _finite(raw["swap_short"], "swap_short")
    swap_mode = _integer(raw["swap_mode"], "swap_mode")
    rollover = _integer(raw["swap_rollover3days"], "swap_rollover3days", low=0, high=6)
    base = _currency(raw["currency_base"], "currency_base")
    profit = _currency(raw["currency_profit"], "currency_profit")
    margin = _currency(raw["currency_margin"], "currency_margin")
    contract_size = _positive(raw["trade_contract_size"], "trade_contract_size")
    point = _positive(raw["point"], "point")
    digits = _integer(raw["digits"], "digits", low=0, high=_MAX_DIGITS)
    spread = _integer(raw["spread"], "spread", low=0)
    if name != broker:
        raise _Unavailable("BROKER_NAME_MISMATCH")
    if swap_mode not in SWAP_MODE_NAMES:
        raise _Unavailable("SWAP_MODE_UNKNOWN")
    if base + profit != canonical:
        raise _Unavailable("CURRENCY_MISMATCH")
    expected_point = 10.0 ** -digits
    if expected_point == 0 or not math.isclose(point, expected_point, rel_tol=1e-9, abs_tol=0):
        raise _Unavailable("POINT_DIGITS_MISMATCH")
    return {
        "canonical_symbol": canonical, "broker_symbol": broker, "status": CAPTURED,
        "swap_long": swap_long, "swap_short": swap_short,
        "swap_mode": swap_mode, "swap_mode_name": SWAP_MODE_NAMES[swap_mode],
        "swap_rollover3days": rollover, "swap_rollover3days_name": DAY_OF_WEEK_NAMES[rollover],
        "currency_base": base, "currency_profit": profit, "currency_margin": margin,
        "trade_contract_size": contract_size, "point": point, "digits": digits, "spread_points": spread,
    }


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or not value.isprintable():
        raise _Unavailable(f"FIELD_INVALID:{name}")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Unavailable(f"FIELD_INVALID:{name}")
    try:
        number = float(value)
    except OverflowError:
        raise _Unavailable(f"FIELD_INVALID:{name}") from None
    if not math.isfinite(number):
        raise _Unavailable(f"FIELD_INVALID:{name}")
    return number


def _positive(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise _Unavailable(f"FIELD_INVALID:{name}")
    return number


def _integer(value: Any, name: str, *, low: int | None = None, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _Unavailable(f"FIELD_INVALID:{name}")
    number = int(value)
    if (low is not None and number < low) or (high is not None and number > high):
        raise _Unavailable(f"FIELD_INVALID:{name}")
    return number


def _currency(value: Any, name: str) -> str:
    text = _text(value, name).upper()
    if len(text) != 3 or not text.isascii() or not text.isalpha():
        raise _Unavailable(f"FIELD_INVALID:{name}")
    return text


# --------------------------------------------------------------------------- payload and hashes


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _assemble(records: Mapping[str, Mapping[str, Any]], captured_at_utc: str, server_time: str, enum_constants_checked: bool) -> dict[str, Any]:
    instruments = {canonical: dict(records[canonical]) for canonical in sorted(records)}
    captured = sum(1 for record in instruments.values() if record["status"] == CAPTURED)
    unavailable = len(instruments) - captured
    status = CAPTURED if unavailable == 0 else (UNAVAILABLE if captured == 0 else PARTIAL)
    # Capture time and spread move every run; the terms hash changes only with the terms.
    terms = {canonical: {key: value for key, value in record.items() if key != "spread_points"}
             for canonical, record in instruments.items()}
    content = SafetyEnvelope().seal({
        "schema_version": SWAP_SNAPSHOT_SCHEMA_VERSION,
        "source": SWAP_SNAPSHOT_SOURCE,
        "captured_at_utc": captured_at_utc,
        "mt5_server_time": server_time,
        "status": status,
        "instrument_count": len(instruments),
        "captured_count": captured,
        "unavailable_count": unavailable,
        "symbols": list(instruments),
        "instruments": instruments,
        "enum_constants_checked": enum_constants_checked,
        "account_data_read": False,
        "swap_terms_hash": _digest({"schema_version": SWAP_SNAPSHOT_SCHEMA_VERSION, "instruments": terms}),
    }, full=True)
    return {**content, "payload_sha256": _digest(content)}


def _rebuild_record(canonical: str, record: Any) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise InstrumentError("swap snapshot record must be a mapping", source=_SOURCE)
    broker = record.get("broker_symbol")
    status = record.get("status")
    if status == UNAVAILABLE:
        reason = record.get("reason")
        if not isinstance(reason, str) or reason not in UNAVAILABLE_REASONS:
            raise InstrumentError("swap snapshot unavailability reason is not a known code", source=_SOURCE)
        return _unavailable(canonical, broker, reason)
    if status != CAPTURED:
        raise InstrumentError("swap snapshot record status must be CAPTURED or UNAVAILABLE", source=_SOURCE)
    info = {name: record.get(field, _MISSING) for name, field in SYMBOL_INFO_FIELDS.items()}
    if any(value is _MISSING for value in info.values()):
        raise InstrumentError("swap snapshot record is incomplete", source=_SOURCE)
    try:
        return _captured(canonical, broker, info)
    except _Unavailable:
        raise InstrumentError("swap snapshot record holds invalid swap terms", source=_SOURCE) from None


def verify_swap_snapshot(payload: Any) -> dict[str, Any]:
    """Return the payload if its schema, every record and both hashes are exact.

    Every field is recomputed from the recorded terms and compared through
    canonical JSON, so a changed value, an altered type (``5.0`` for ``5``,
    ``true`` for ``1``), an added or missing field or a stale hash is rejected.
    """

    if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_KEYS:
        raise InstrumentError("invalid swap snapshot schema", source=_SOURCE)
    if payload["schema_version"] != SWAP_SNAPSHOT_SCHEMA_VERSION or payload["source"] != SWAP_SNAPSHOT_SOURCE:
        raise InstrumentError("unsupported swap snapshot version or source", source=_SOURCE)
    captured_text = payload["captured_at_utc"]
    try:
        captured = datetime.fromisoformat(captured_text)
    except (TypeError, ValueError):
        raise InstrumentError("invalid swap snapshot capture time", source=_SOURCE) from None
    if captured.utcoffset() is None:
        raise InstrumentError("swap snapshot capture time must carry a UTC offset", source=_SOURCE)
    server_time = _canonical_server_time(payload["mt5_server_time"])
    enum_constants_checked = payload["enum_constants_checked"]
    if not isinstance(enum_constants_checked, bool):
        raise InstrumentError("enum_constants_checked must be a boolean", source=_SOURCE)
    entries = payload["instruments"]
    if not isinstance(entries, Mapping) or not entries:
        raise InstrumentError("swap snapshot instruments must be a nonempty mapping", source=_SOURCE)
    brokers = {}
    for canonical, record in entries.items():
        if not isinstance(record, Mapping):
            raise InstrumentError("swap snapshot record must be a mapping", source=_SOURCE)
        brokers[canonical] = record.get("broker_symbol")
    aliases = validate_symbol_map(brokers)
    if set(aliases) != set(entries):
        raise InstrumentError("swap snapshot keys must be canonical upper-case symbols", source=_SOURCE)
    records = {canonical: _rebuild_record(canonical, entries[canonical]) for canonical in aliases}
    rebuilt = _assemble(records, captured.astimezone(timezone.utc).isoformat(), server_time, enum_constants_checked)
    try:
        identical = _canonical_json(dict(payload)) == _canonical_json(rebuilt)
    except (TypeError, ValueError):
        identical = False
    if not identical:
        raise InstrumentError("swap snapshot fields or hashes do not match", source=_SOURCE)
    return rebuilt


def write_swap_snapshot(payload: Mapping[str, Any], path: str | Path) -> Path:
    """Publish a verified, fsynced snapshot exclusively; never replace evidence.

    The caller creates the destination directory. Linking the temporary file
    publishes all bytes at once and fails if the destination exists.
    Filesystems without hard-link support fail closed.
    """

    verified = verify_swap_snapshot(payload)
    destination = Path(path)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("swap snapshot destination already exists")
    temporary: Path | None = None
    try:
        content = (_canonical_json(verified) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(prefix=".swap-snapshot-", suffix=".tmp", dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    except FileExistsError:
        raise FileExistsError("swap snapshot destination already exists") from None
    except (OSError, ValueError):
        # The OS message may name local paths.
        raise OSError("cannot publish swap snapshot; destination must be new and writable") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def _reject_constant(token: str) -> Any:
    raise ValueError("non-finite JSON number")


def read_swap_snapshot(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object,
                             parse_constant=_reject_constant)
    except (OSError, ValueError, UnicodeError):
        raise InstrumentError("cannot read valid swap snapshot JSON", source=_SOURCE) from None
    return verify_swap_snapshot(payload)


# --------------------------------------------------------------------------- measured carry


def _carry_error(message: str, reason: str) -> InstrumentError:
    return InstrumentError(message, source=_SOURCE, detail={"reason": reason})


def _price(value: Any) -> float:
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise _carry_error("carry needs a finite positive price for the pair", "PRICE_INVALID")
    return float(value)


def annualised_swap_carry(record: Mapping[str, Any], *, price: float) -> dict[str, Any]:
    """Approximate annual carry, in percent of notional, from broker swap points.

    Only ``SWAP_MODE_POINTS`` is converted: a point swap of ``s`` on one lot is
    ``s * point * contract_size`` in the quote currency per rollover, valued in
    USD exactly like ``derive_tick_value`` (USD-quoted pairs directly, USD-base
    pairs through ``price``, the pair's own price). Notional is one lot at
    ``price`` in USD. A week holds five rollovers, one of them triple, so the
    daily amount is charged on average once per calendar day: ``* 365``. For
    either kind of pair the rate reduces to ``s * point / price * 365``.

    ``implied_symmetric_markup_bps_per_year`` is ``-(long% + short%) / 2`` in
    basis points: the broker's mark-up if it is applied symmetrically around
    the interest differential (the quantity the daily study assumed at 75).

    Approximation limits: holiday extra rollovers, intra-year term changes and
    price drift are ignored; the price is the caller's. No rate or mark-up is
    assumed, so the result is labelled ``OBSERVED`` with ``carry_assumed``
    False: it is measured from the broker's own swap terms.
    """

    if not isinstance(record, Mapping):
        raise _carry_error("swap record must be a mapping", "RECORD_INVALID")
    canonical = record.get("canonical_symbol")
    if record.get("status") != CAPTURED:
        reason = record.get("reason")
        raise _carry_error("swap terms were not captured for this symbol",
                           reason if reason in UNAVAILABLE_REASONS else "RECORD_UNAVAILABLE")
    try:
        if not isinstance(canonical, str):
            raise InstrumentError("swap record has no canonical symbol", source=_SOURCE)
        validate_symbol_map({canonical: record.get("broker_symbol")})
        rebuilt = _rebuild_record(canonical, record)
        intact = _canonical_json(dict(record)) == _canonical_json(rebuilt)
    except (InstrumentError, TypeError, ValueError):
        intact = False
    if not intact:
        raise _carry_error("swap record is not an intact captured record", "RECORD_INVALID")
    if rebuilt["swap_mode"] != SWAP_MODE_POINTS:
        name = rebuilt["swap_mode_name"]
        raise _carry_error(f"swap mode {name} is not converted to annual carry; only POINTS is",
                           f"SWAP_MODE_NOT_CONVERTED:{name}")
    if rebuilt["swap_rollover3days"] not in _WEEKDAYS:
        raise _carry_error("triple-swap day is not a weekday; the 365-day annualisation does not apply",
                           "TRIPLE_SWAP_DAY_NOT_WEEKDAY")
    value = _price(price)
    base, quote = rebuilt["currency_base"], rebuilt["currency_profit"]
    if _CARRY_CURRENCY not in (base, quote) or base == quote:
        raise _carry_error(f"{base}{quote}: no {_CARRY_CURRENCY} conversion rate for a cross; carry is not converted",
                           "CROSS_WITHOUT_USD_RATE")
    contract_size = rebuilt["trade_contract_size"]
    usd_per_point = derive_tick_value(currency_base=base, currency_quote=quote, tick_size=rebuilt["point"],
                                      contract_size=contract_size, price=value, account_currency=_CARRY_CURRENCY)
    notional = contract_size if base == _CARRY_CURRENCY else contract_size * value
    long_per_day = rebuilt["swap_long"] * usd_per_point
    short_per_day = rebuilt["swap_short"] * usd_per_point
    long_percent = long_per_day * DAYS_PER_YEAR / notional * 100.0
    short_percent = short_per_day * DAYS_PER_YEAR / notional * 100.0
    result = {
        "carry_status": OBSERVED,
        "carry_assumed": False,
        "carry_source": SWAP_SNAPSHOT_SOURCE,
        "canonical_symbol": rebuilt["canonical_symbol"],
        "broker_symbol": rebuilt["broker_symbol"],
        "swap_mode_name": rebuilt["swap_mode_name"],
        "swap_rollover3days_name": rebuilt["swap_rollover3days_name"],
        "price": value,
        "price_source": "caller",
        "carry_currency": _CARRY_CURRENCY,
        "days_per_year": DAYS_PER_YEAR,
        "usd_per_point_per_lot": usd_per_point,
        "notional_usd_per_lot": notional,
        "long_usd_per_lot_per_day": long_per_day,
        "short_usd_per_lot_per_day": short_per_day,
        "long_annual_percent_of_notional": long_percent,
        "short_annual_percent_of_notional": short_percent,
        "implied_symmetric_markup_bps_per_year": -(long_percent + short_percent) / 2.0 * 100.0,
    }
    if not all(math.isfinite(item) for item in result.values() if isinstance(item, float)):
        raise _carry_error("carry is not a finite number", "CARRY_NOT_FINITE")
    return result


def snapshot_carry(payload: Mapping[str, Any], prices: Mapping[str, float]) -> dict[str, Any]:
    """Convert every captured symbol of a verified snapshot; fail closed per symbol.

    ``prices`` maps canonical symbols to the pair's price. A symbol without a
    price, an unavailable record or a conversion the helper refuses is reported
    as ``UNAVAILABLE`` with a closed reason code, never estimated.
    """

    verified = verify_swap_snapshot(payload)
    if not isinstance(prices, Mapping) or any(not isinstance(key, str) for key in prices):
        raise InstrumentError("prices must map canonical symbols to numbers", source=_SOURCE)
    by_symbol = {key.upper(): value for key, value in prices.items()}
    if len(by_symbol) != len(prices):
        raise InstrumentError("prices name the same symbol twice", source=_SOURCE)
    carry: dict[str, Any] = {}
    for canonical, record in verified["instruments"].items():
        if record["status"] != CAPTURED:
            carry[canonical] = {"carry_status": UNAVAILABLE, "reason": record["reason"]}
        elif canonical not in by_symbol:
            carry[canonical] = {"carry_status": UNAVAILABLE, "reason": "PRICE_MISSING"}
        else:
            try:
                carry[canonical] = annualised_swap_carry(record, price=by_symbol[canonical])
            except InstrumentError as error:
                carry[canonical] = {"carry_status": UNAVAILABLE, "reason": str(error.detail.get("reason") or "CARRY_UNAVAILABLE")}
    return SafetyEnvelope().seal({
        "schema_version": SWAP_CARRY_SCHEMA_VERSION,
        "source": SWAP_SNAPSHOT_SOURCE,
        "payload_sha256": verified["payload_sha256"],
        "swap_terms_hash": verified["swap_terms_hash"],
        "captured_at_utc": verified["captured_at_utc"],
        "mt5_server_time": verified["mt5_server_time"],
        "carry": carry,
        "account_data_read": False,
    }, full=True)


__all__ = [
    "DAYS_PER_YEAR",
    "DAY_OF_WEEK_NAMES",
    "SWAP_CARRY_SCHEMA_VERSION",
    "SWAP_MODE_NAMES",
    "SWAP_SNAPSHOT_SCHEMA_VERSION",
    "SWAP_SNAPSHOT_SOURCE",
    "SYMBOL_INFO_FIELDS",
    "UNAVAILABLE_REASONS",
    "annualised_swap_carry",
    "build_swap_snapshot",
    "capture_swap_record",
    "check_mt5_enum_constants",
    "read_swap_snapshot",
    "snapshot_carry",
    "verify_swap_snapshot",
    "write_swap_snapshot",
]
