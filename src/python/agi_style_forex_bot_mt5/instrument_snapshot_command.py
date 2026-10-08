"""Read-only terminal metadata capture command; never requests account data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core.clock import Clock, resolve_clock
from .core.safety import SafetyEnvelope
from .instrument_registry_builder import build_instrument_registry_snapshot


def capture_instrument_snapshot(*, client: Any, symbol_map_path: Path, output_path: Path, clock: Clock | None = None) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError("instrument snapshot destination already exists")
    symbols = json.loads(symbol_map_path.read_text(encoding="utf-8"))
    if not isinstance(symbols, dict) or not symbols:
        raise ValueError("broker symbol map must be a nonempty JSON object")
    if not output_path.parent.is_dir():
        raise ValueError("snapshot output parent directory must already exist")
    initialized = False
    try:
        if client.initialize() is not True:
            raise RuntimeError("read-only terminal connection unavailable")
        initialized = True
        snapshot = build_instrument_registry_snapshot(client=client, symbols=symbols, captured_at_utc=resolve_clock(clock).now_utc())
        snapshot.write(output_path)
        return SafetyEnvelope().seal({
            "mode": "build-instrument-registry", "status": "CAPTURED",
            "instrument_count": len(symbols), "metadata_hash": snapshot.metadata_hash,
            "instrument_snapshot_hash": snapshot.snapshot_hash,
            "captured_at_utc": snapshot.as_dict()["captured_at_utc"],
            "output": str(output_path), "historical_metadata_verified": False,
        }, full=True)
    finally:
        if initialized:
            client.shutdown()
