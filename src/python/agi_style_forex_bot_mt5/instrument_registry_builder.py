"""Capture broker instrument metadata through an injected read-only client.

This module neither imports MetaTrader5 nor starts or authenticates a terminal.
Only ``symbol_info`` is called. Caller-supplied clients own their connection.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Mapping, Protocol

from .core.instruments.registry import InstrumentRegistry, InstrumentSpec, spec_from_symbol_info
from .core.instruments.snapshot import InstrumentRegistrySnapshot
from .core.operational_state.errors import InstrumentError


class SymbolInfoClient(Protocol):
    def symbol_info(self, symbol: str) -> Any: ...


def build_instrument_registry_snapshot(
    *,
    client: SymbolInfoClient,
    symbols: Mapping[str, str],
    captured_at_utc: datetime,
) -> InstrumentRegistrySnapshot:
    """Collect all requested FX instruments or return no snapshot on any error.

    ``symbols`` explicitly maps canonical pairs (EURUSD) to exact broker names
    (EURUSD.raw). No suffix guessing, alias discovery, account calls or mutable
    terminal operations are performed. Metadata extra fields are never copied.
    """

    if not isinstance(captured_at_utc, datetime) or captured_at_utc.utcoffset() is None:
        raise InstrumentError("captured_at_utc must be a timezone-aware datetime", source="instrument_registry_builder")
    if not isinstance(symbols, Mapping) or not symbols:
        raise InstrumentError("a nonempty canonical-to-broker symbol mapping is required", source="instrument_registry_builder")
    aliases: dict[str, str] = {}
    for canonical, broker in symbols.items():
        if not isinstance(canonical, str) or not re.fullmatch(r"[A-Za-z]{6}", canonical):
            raise InstrumentError("canonical Forex symbol must contain six letters", source="instrument_registry_builder")
        if not isinstance(broker, str) or not re.fullmatch(r"[A-Za-z0-9_.#+/-]{1,64}", broker):
            raise InstrumentError("broker symbol must be an explicit supported instrument name", source="instrument_registry_builder")
        key = canonical.upper()
        if key in aliases or broker in aliases.values():
            raise InstrumentError("duplicate canonical or broker symbol mapping", source="instrument_registry_builder")
        aliases[key] = broker
    specs: list[InstrumentSpec] = []
    for canonical, broker in sorted(aliases.items()):
        try:
            info = client.symbol_info(broker)
            spec = spec_from_symbol_info(canonical, info, broker_symbol=broker)
        except Exception:
            # A client exception may contain credentials, terminal paths or
            # server names. Do not include it or its chained traceback.
            raise InstrumentError("symbol_info capture failed or returned invalid instrument metadata", source="instrument_registry_builder", detail={"symbol": canonical}) from None
        if spec.currency_base + spec.currency_quote != canonical:
            raise InstrumentError("captured currencies do not match canonical Forex symbol", source="instrument_registry_builder")
        if spec.digits > 323:
            raise InstrumentError("captured digits exceed representable positive point precision", source="instrument_registry_builder")
        expected_point = 10.0 ** -spec.digits
        ticks_in_points = spec.tick_size / spec.point
        if expected_point == 0 or not math.isclose(spec.point, expected_point, rel_tol=1e-9, abs_tol=0):
            raise InstrumentError("captured point does not match digits", source="instrument_registry_builder")
        if not math.isfinite(ticks_in_points) or not math.isclose(ticks_in_points, round(ticks_in_points), rel_tol=0, abs_tol=1e-8) or ticks_in_points < 1:
            raise InstrumentError("captured tick_size is not an integral number of points", source="instrument_registry_builder")
        if spec.volume_step > spec.max_volume:
            raise InstrumentError("captured volume_step exceeds maximum volume", source="instrument_registry_builder")
        specs.append(spec)
    return InstrumentRegistrySnapshot(registry=InstrumentRegistry.from_specs(specs), captured_at_utc=captured_at_utc)
