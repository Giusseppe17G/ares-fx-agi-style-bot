"""Strict JSONL transport for explicit-quote research replays, with no I/O to MT5."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterator, Mapping

import pandas as pd

from ..contracts import MarketSnapshot


class ReplayInputError(ValueError):
    """Replay transport has an invalid or ambiguous field."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReplayInputError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ReplayInputError("non-finite JSON number")


def _shape(value: Any, required: set[str], *, optional: set[str] | None = None) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - (optional or set()):
        raise ReplayInputError("missing or unknown replay fields")
    return value


def _utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ReplayInputError("timestamp must be an ISO string with timezone")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        raise ReplayInputError("invalid timestamp") from None
    if instant.utcoffset() is None:
        raise ReplayInputError("timestamp timezone is required")
    return instant.astimezone(timezone.utc)


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ReplayInputError("nonempty replay identifier is required")
    return value


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReplayInputError("finite JSON number is required")
    return value


def _quote(value: Any) -> MarketSnapshot:
    payload = dict(_shape(value, {field.name for field in fields(MarketSnapshot)}))
    for name in ("symbol", "timeframe"):
        _text(payload[name])
    payload["timestamp_utc"] = _utc(payload["timestamp_utc"])
    for name in set(payload) - {"symbol", "timeframe", "timestamp_utc"}:
        _number(payload[name])
    for name in ("digits", "stops_level_points", "freeze_level_points"):
        if type(payload[name]) is not int:
            raise ReplayInputError("quote precision and broker levels must be integers")
    snapshot = MarketSnapshot(**payload)
    snapshot.validate()
    return snapshot


def _bars(value: Any, *, symbol: str, timeframe: str) -> pd.DataFrame:
    if not isinstance(value, list) or not value:
        raise ReplayInputError("closed bars must be a nonempty array")
    rows = []
    required = {"timestamp_utc", "open", "high", "low", "close", "volume", "spread_points"}
    for row in value:
        record = dict(_shape(row, required, optional={"symbol", "timeframe"}))
        record["timestamp_utc"] = _utc(record["timestamp_utc"])
        for name in required - {"timestamp_utc"}:
            _number(record[name])
        for name, expected in (("symbol", symbol), ("timeframe", timeframe)):
            if name in record and record[name] != expected:
                raise ReplayInputError("bar symbol/timeframe mismatch")
            record[name] = expected
        rows.append(record)
    return pd.DataFrame(rows)


def event_from_mapping(value: Any):
    # Import lazily: reading the transport cannot instantiate a terminal client.
    from .stateful_replay import ClosedBarInput, ReplayEvidence, StatefulReplayEvent

    payload = _shape(value, {"event_id", "timestamp_utc", "quotes", "decisions", "evidence"})
    if not isinstance(payload["quotes"], dict) or not payload["quotes"]:
        raise ReplayInputError("an explicit quote map is required")
    quotes = {_text(symbol): _quote(quote) for symbol, quote in payload["quotes"].items()}
    if any(symbol != quote.symbol for symbol, quote in quotes.items()):
        raise ReplayInputError("quote key/symbol mismatch")
    if not isinstance(payload["decisions"], list):
        raise ReplayInputError("decisions must be an array")
    decisions = []
    for item in payload["decisions"]:
        item = _shape(item, {"symbol", "timeframe", "bars"})
        symbol, timeframe = _text(item["symbol"]), _text(item["timeframe"])
        decisions.append(ClosedBarInput(symbol=symbol, timeframe=timeframe,
                                       bars=_bars(item["bars"], symbol=symbol, timeframe=timeframe)))
    if not isinstance(payload["evidence"], dict):
        raise ReplayInputError("evidence must be a mapping")
    evidence = {}
    for symbol, item in payload["evidence"].items():
        item = _shape(item, {"observed_at_utc", "broker_readiness_score", "correlation"})
        correlation = item["correlation"]
        evidence[_text(symbol)] = ReplayEvidence(
            observed_at_utc=_utc(item["observed_at_utc"]),
            broker_readiness_score=_number(item["broker_readiness_score"]),
            correlation=None if correlation is None else _number(correlation),
        )
    return StatefulReplayEvent(event_id=_text(payload["event_id"]), timestamp_utc=_utc(payload["timestamp_utc"]),
                               quotes=quotes, decisions=tuple(decisions), evidence=evidence)


def load_replay_events(path: str | Path) -> Iterator[Any]:
    """Read one event per line; never repair, sort or fill missing market data.

    Runtime chronology, causal availability and broker evidence checks belong
    to the shared replay engine. Input exceptions identify line numbers without
    echoing raw input fields that might contain sensitive local data.
    """
    found = False
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                if not line.strip():
                    raise ReplayInputError("blank JSONL event")
                value = json.loads(line, object_pairs_hook=_object, parse_constant=_reject_constant)
                event = event_from_mapping(value)
            except (ValueError, TypeError, OverflowError):
                raise ReplayInputError(f"invalid replay event on line {line_number}") from None
            found = True
            yield event
    if not found:
        raise ReplayInputError("replay file is empty")
