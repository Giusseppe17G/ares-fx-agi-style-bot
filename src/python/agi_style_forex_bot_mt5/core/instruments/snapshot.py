"""Frozen instrument metadata with reproducible content hashes, not signatures."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..operational_state.errors import InstrumentError
from .registry import InstrumentRegistry, _unique_json_object, spec_from_mapping


INSTRUMENT_SNAPSHOT_VERSION = "1.0"
INSTRUMENT_SNAPSHOT_SOURCE = "mt5:symbol_info"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def instrument_metadata_hash(registry: InstrumentRegistry) -> str:
    """Hash normalized fields, including broker aliases and declared sources."""

    return _digest(registry.as_dict()["instruments"])


@dataclass(frozen=True)
class InstrumentRegistrySnapshot:
    registry: InstrumentRegistry
    captured_at_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.registry, InstrumentRegistry) or not self.registry.specs:
            raise InstrumentError("snapshot requires a nonempty instrument registry", source="instrument_snapshot")
        if not isinstance(self.captured_at_utc, datetime) or self.captured_at_utc.utcoffset() is None:
            raise InstrumentError("captured_at_utc must be a timezone-aware datetime", source="instrument_snapshot")
        object.__setattr__(self, "captured_at_utc", self.captured_at_utc.astimezone(timezone.utc))
        for spec in self.registry.specs.values():
            if spec.source != INSTRUMENT_SNAPSHOT_SOURCE:
                raise InstrumentError("snapshot requires observed MT5 symbol_info metadata", source="instrument_snapshot")

    @property
    def metadata_hash(self) -> str:
        return instrument_metadata_hash(self.registry)

    @property
    def snapshot_hash(self) -> str:
        return _digest(self._content())

    def _content(self) -> dict[str, Any]:
        return {
            "schema_version": INSTRUMENT_SNAPSHOT_VERSION,
            "source": INSTRUMENT_SNAPSHOT_SOURCE,
            "captured_at_utc": self.captured_at_utc.isoformat(),
            "metadata_hash": self.metadata_hash,
            **self.registry.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self._content()
        return {**payload, "snapshot_hash": _digest(payload)}

    def write(self, path: str | Path) -> Path:
        """Publish a complete, fsynced file exclusively; never replace evidence.

        The caller creates the destination directory. Linking the temporary
        file publishes all bytes at once and fails if the destination exists.
        Filesystems without hard-link support fail closed.
        """

        destination = Path(path)
        temporary: Path | None = None
        try:
            content = (_canonical_json(self.as_dict()) + "\n").encode("utf-8")
            with tempfile.NamedTemporaryFile(prefix=".instruments-", suffix=".tmp", dir=destination.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, destination)
        except (OSError, ValueError):
            raise InstrumentError("cannot publish instrument snapshot; destination must be new and writable", source="instrument_snapshot") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return destination

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "InstrumentRegistrySnapshot":
        """Require exact schema, valid metadata and matching content hashes."""

        required = {"schema_version", "source", "captured_at_utc", "metadata_hash", "instrument_count", "symbols", "instruments", "snapshot_hash"}
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise InstrumentError("invalid instrument snapshot schema", source="instrument_snapshot")
        if payload["schema_version"] != INSTRUMENT_SNAPSHOT_VERSION or payload["source"] != INSTRUMENT_SNAPSHOT_SOURCE:
            raise InstrumentError("unsupported instrument snapshot version or source", source="instrument_snapshot")
        try:
            captured = datetime.fromisoformat(payload["captured_at_utc"])
        except (TypeError, ValueError):
            raise InstrumentError("invalid snapshot capture time", source="instrument_snapshot") from None
        entries = payload["instruments"]
        if not isinstance(entries, Mapping):
            raise InstrumentError("snapshot instruments must be a mapping", source="instrument_snapshot")
        registry = InstrumentRegistry.from_specs(spec_from_mapping(key, values) for key, values in entries.items())
        snapshot = cls(registry=registry, captured_at_utc=captured)
        if type(payload["instrument_count"]) is not int or dict(payload) != snapshot.as_dict():
            raise InstrumentError("instrument snapshot fields or hashes do not match", source="instrument_snapshot")
        return snapshot

    @classmethod
    def read(cls, path: str | Path) -> "InstrumentRegistrySnapshot":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)
        except (OSError, ValueError, UnicodeError):
            raise InstrumentError("cannot read valid instrument snapshot JSON", source="instrument_snapshot") from None
        return cls.from_mapping(payload)
