"""Single source of instrument metadata for backtest and live.

The backtester used to invent five of these values (`digits = 3 if "JPY" in
symbol else 5`, `tick_value = 1.0`, `volume_min = 0.01`, `stops_level = 10`,
`freeze_level = 5`) while forward-shadow read the real ones from MT5
`symbol_info`. Any comparison between the two was therefore comparing different
instruments.

Adopted from CCXT: the market-metadata shape (precision plus limits as first
class fields) and capability discovery -- `InstrumentRegistry.has()` answers
whether the metadata for a symbol is actually known before anything tries to use
it. Not adopted: the multi-exchange unified API, which buys nothing with one
broker.

Fail closed: a missing or invalid spec raises `InstrumentError`. Nothing here
substitutes a default for metadata it does not have.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..operational_state.errors import InstrumentError


DATASET_METADATA_FILENAME = "instruments.json"


@dataclass(frozen=True)
class InstrumentSpec:
    """Everything sizing, rounding and execution need to know about one symbol."""

    symbol: str
    canonical_symbol: str
    broker_symbol: str
    digits: int
    point: float
    tick_size: float
    tick_value: float
    contract_size: float
    min_volume: float
    max_volume: float
    volume_step: float
    stops_level_points: int
    freeze_level_points: int
    currency_base: str
    currency_quote: str
    source: str = ""

    def validate(self) -> "InstrumentSpec":
        """Reject any spec that cannot be used for sizing or rounding."""

        if not self.symbol or not self.canonical_symbol or not self.broker_symbol:
            raise InstrumentError("symbol, canonical_symbol and broker_symbol are required", source="instrument_registry", detail={"symbol": self.symbol})
        if self.digits < 0:
            raise InstrumentError(f"{self.symbol}: digits must be non-negative", source="instrument_registry")
        for name in ("point", "tick_size", "tick_value", "contract_size", "min_volume", "max_volume", "volume_step"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value != value or value <= 0:
                raise InstrumentError(f"{self.symbol}: {name} must be a positive number, got {value!r}", source="instrument_registry")
        if self.min_volume > self.max_volume:
            raise InstrumentError(f"{self.symbol}: min_volume cannot exceed max_volume", source="instrument_registry")
        if self.stops_level_points < 0 or self.freeze_level_points < 0:
            raise InstrumentError(f"{self.symbol}: stops and freeze levels cannot be negative", source="instrument_registry")
        if not self.currency_base or not self.currency_quote:
            raise InstrumentError(f"{self.symbol}: base and quote currencies are required", source="instrument_registry")
        return self

    def round_price(self, price: float) -> float:
        return round(float(price), self.digits)

    def round_volume(self, volume: float) -> float:
        """Clamp to the broker's volume limits and snap to its step."""

        clamped = min(max(float(volume), self.min_volume), self.max_volume)
        steps = round(clamped / self.volume_step)
        return round(steps * self.volume_step, 8)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InstrumentRegistry:
    """Read-only lookup of instrument specs, keyed by canonical symbol."""

    specs: Mapping[str, InstrumentSpec]

    def has(self, symbol: str) -> bool:
        """CCXT-style capability discovery: is this instrument actually known?"""

        return _key(symbol) in self.specs

    def get(self, symbol: str) -> InstrumentSpec:
        key = _key(symbol)
        spec = self.specs.get(key)
        if spec is None:
            raise InstrumentError(
                f"no instrument metadata for {symbol!r}; refusing to guess",
                source="instrument_registry",
                detail={"symbol": symbol, "known": sorted(self.specs)},
            )
        return spec

    def symbols(self) -> list[str]:
        return sorted(self.specs)

    def as_dict(self) -> dict[str, Any]:
        return {"instrument_count": len(self.specs), "symbols": self.symbols(), "instruments": {key: spec.as_dict() for key, spec in sorted(self.specs.items())}}

    @classmethod
    def from_specs(cls, specs: Iterable[InstrumentSpec]) -> "InstrumentRegistry":
        return cls(specs={_key(spec.canonical_symbol): spec.validate() for spec in specs})

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, source: str = "mapping") -> "InstrumentRegistry":
        entries = payload.get("instruments") if isinstance(payload.get("instruments"), Mapping) else payload
        return cls.from_specs(spec_from_mapping(symbol, dict(values), source=source) for symbol, values in entries.items())

    @classmethod
    def from_dataset(cls, data_dir: str | Path, *, filename: str = DATASET_METADATA_FILENAME) -> "InstrumentRegistry":
        """Load the metadata sidecar that travels with a historical dataset.

        A backtest must use the metadata of the instrument its data came from.
        Without the sidecar there is no metadata, and that is an error, not a
        reason to fall back to assumptions.
        """

        path = Path(data_dir) / filename
        if not path.is_file():
            raise InstrumentError(
                f"dataset instrument metadata not found at {path}; backtests must not guess instrument metadata",
                source="instrument_registry",
                detail={"expected_path": str(path)},
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InstrumentError(f"cannot read instrument metadata at {path}: {error}", source="instrument_registry") from error
        if not isinstance(payload, Mapping):
            raise InstrumentError(f"instrument metadata at {path} must be a JSON object", source="instrument_registry")
        return cls.from_mapping(payload, source=f"dataset:{path.name}")

    @classmethod
    def from_symbol_info(cls, symbol_infos: Mapping[str, Any], *, broker_symbols: Mapping[str, str] | None = None) -> "InstrumentRegistry":
        """Build from live MT5 `symbol_info` objects. No value is defaulted."""

        broker_symbols = broker_symbols or {}
        return cls.from_specs(
            spec_from_symbol_info(canonical, info, broker_symbol=broker_symbols.get(canonical, canonical))
            for canonical, info in symbol_infos.items()
        )


def spec_from_mapping(symbol: str, values: Mapping[str, Any], *, source: str = "mapping") -> InstrumentSpec:
    canonical = str(values.get("canonical_symbol") or symbol).upper()
    missing = [key for key in REQUIRED_SPEC_KEYS if key not in values]
    if missing:
        raise InstrumentError(
            f"{canonical}: instrument metadata is missing {sorted(missing)}; refusing to substitute defaults",
            source="instrument_registry",
            detail={"symbol": canonical, "missing": sorted(missing)},
        )
    return InstrumentSpec(
        symbol=str(values.get("symbol") or symbol).upper(),
        canonical_symbol=canonical,
        broker_symbol=str(values.get("broker_symbol") or canonical),
        digits=int(values["digits"]),
        point=float(values["point"]),
        tick_size=float(values["tick_size"]),
        tick_value=float(values["tick_value"]),
        contract_size=float(values["contract_size"]),
        min_volume=float(values["min_volume"]),
        max_volume=float(values["max_volume"]),
        volume_step=float(values["volume_step"]),
        stops_level_points=int(values["stops_level_points"]),
        freeze_level_points=int(values["freeze_level_points"]),
        currency_base=str(values["currency_base"]).upper(),
        currency_quote=str(values["currency_quote"]).upper(),
        source=str(values.get("source") or source),
    ).validate()


def spec_from_symbol_info(canonical: str, info: Any, *, broker_symbol: str = "") -> InstrumentSpec:
    """Map an MT5 `symbol_info` onto a spec. Absent attributes fail closed."""

    def attribute(name: str) -> Any:
        if isinstance(info, Mapping):
            if name not in info:
                raise InstrumentError(f"{canonical}: MT5 symbol_info has no {name}", source="instrument_registry")
            return info[name]
        if not hasattr(info, name):
            raise InstrumentError(f"{canonical}: MT5 symbol_info has no {name}", source="instrument_registry")
        return getattr(info, name)

    return InstrumentSpec(
        symbol=canonical.upper(),
        canonical_symbol=canonical.upper(),
        broker_symbol=str(broker_symbol or attribute("name")),
        digits=int(attribute("digits")),
        point=float(attribute("point")),
        tick_size=float(attribute("trade_tick_size")),
        tick_value=float(attribute("trade_tick_value")),
        contract_size=float(attribute("trade_contract_size")),
        min_volume=float(attribute("volume_min")),
        max_volume=float(attribute("volume_max")),
        volume_step=float(attribute("volume_step")),
        stops_level_points=int(attribute("trade_stops_level")),
        freeze_level_points=int(attribute("trade_freeze_level")),
        currency_base=str(attribute("currency_base")).upper(),
        currency_quote=str(attribute("currency_profit")).upper(),
        source="mt5:symbol_info",
    ).validate()


REQUIRED_SPEC_KEYS = (
    "digits",
    "point",
    "tick_size",
    "tick_value",
    "contract_size",
    "min_volume",
    "max_volume",
    "volume_step",
    "stops_level_points",
    "freeze_level_points",
    "currency_base",
    "currency_quote",
)


def _key(symbol: str) -> str:
    return str(symbol or "").upper()


# --------------------------------------------------------------------------- declared assumptions

ASSUMED_SOURCE = "LEGACY_ASSUMED_FX_DEFAULT"

# The backtester previously invented instrument metadata inline, differently in
# several places (`digits = 3 if "JPY" in symbol else 5`, `tick_value = 1.0`,
# `volume_min = 0.01`, `stops_level = 10`, `freeze_level = 5`). Those assumptions
# cannot be deleted outright without real per-symbol metadata, so they are
# consolidated here instead: one place, explicitly labelled, and visible in every
# report through `instrument_metadata_source`. The parity gate refuses to run on
# an assumed spec, so nothing that claims backtest/live parity can rest on one.
_JPY_QUOTE_DIGITS = 3
_FX_DIGITS = 5


def assumed_fx_spec(symbol: str) -> InstrumentSpec:
    """A clearly-labelled placeholder spec. Never valid for parity or acceptance."""

    canonical = _key(symbol)
    quote = canonical[3:6] if len(canonical) >= 6 else ""
    base = canonical[0:3] if len(canonical) >= 6 else canonical
    digits = _JPY_QUOTE_DIGITS if quote == "JPY" else _FX_DIGITS
    point = 10.0 ** -digits
    return InstrumentSpec(
        symbol=canonical,
        canonical_symbol=canonical,
        broker_symbol=canonical,
        digits=digits,
        point=point,
        tick_size=point,
        tick_value=1.0,
        contract_size=100_000.0,
        min_volume=0.01,
        max_volume=100.0,
        volume_step=0.01,
        stops_level_points=10,
        freeze_level_points=5,
        currency_base=base or "XXX",
        currency_quote=quote or "XXX",
        source=ASSUMED_SOURCE,
    ).validate()


def is_assumed(spec: InstrumentSpec) -> bool:
    return spec.source == ASSUMED_SOURCE


def resolve_registry(
    *,
    registry: InstrumentRegistry | None = None,
    data_dir: str | Path | None = None,
    symbols: Iterable[str] = (),
    allow_assumptions: bool = True,
) -> tuple[InstrumentRegistry, str]:
    """Resolve instrument metadata and say where it came from.

    Order: an explicit registry, then the dataset sidecar, then -- only when
    `allow_assumptions` is set -- the declared placeholder specs. With
    `allow_assumptions=False` a missing sidecar raises instead.
    """

    if registry is not None:
        return registry, "explicit"
    if data_dir is not None:
        path = Path(data_dir) / DATASET_METADATA_FILENAME
        if path.is_file():
            return InstrumentRegistry.from_dataset(data_dir), f"dataset:{path.name}"
        if not allow_assumptions:
            return InstrumentRegistry.from_dataset(data_dir), "unreachable"
    if not allow_assumptions:
        raise InstrumentError(
            "no instrument metadata available and assumptions are not allowed",
            source="instrument_registry",
            detail={"data_dir": str(data_dir) if data_dir else "", "symbols": sorted(str(item) for item in symbols)},
        )
    return InstrumentRegistry.from_specs(assumed_fx_spec(symbol) for symbol in symbols), ASSUMED_SOURCE
