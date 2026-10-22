"""Read-only broker swap capture command; never requests account data or sends orders.

Same safety pattern as ``instrument_snapshot_command``: every argument is
validated before the terminal is touched, only ``initialize``, ``symbol_info``
and ``shutdown`` are called, an existing output is never overwritten, the
output's parent directory must already exist and the summary is sealed by
``SafetyEnvelope``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .broker_swap_snapshot import build_swap_snapshot, check_mt5_enum_constants, write_swap_snapshot
from .core.clock import Clock, resolve_clock
from .core.instruments.registry import _unique_json_object
from .core.safety import SafetyEnvelope
from .instrument_registry_builder import validate_symbol_map
from .utils.mt5_server_time import parse_server_time


MODE = "capture-swap-snapshot"


def prepare_swap_capture(*, symbol_map_path: Path, output_path: Path, mt5_server_time: str) -> dict[str, str]:
    """Validate every argument without any terminal; return the symbol aliases.

    Raises ``FileExistsError`` for an existing output, ``ValueError`` for an
    unreadable or malformed map, a missing output directory or a non-canonical
    server-time convention, and ``InstrumentError`` for an invalid symbol map.
    """

    output_path = Path(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError("swap snapshot destination already exists")
    try:
        canonical_time = parse_server_time(mt5_server_time)
    except ValueError:
        canonical_time = None
    if not isinstance(mt5_server_time, str) or canonical_time != mt5_server_time:
        raise ValueError("MT5_SERVER_TIME must be a canonical declared convention (UTC, NY_CLOSE, EET or UTC+HH:MM)")
    try:
        text = Path(symbol_map_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise ValueError("broker symbol map must be a readable UTF-8 JSON file") from None
    try:
        symbols = json.loads(text, object_pairs_hook=_unique_json_object)
    except ValueError:
        raise ValueError("broker symbol map must be valid JSON without duplicate keys") from None
    if not isinstance(symbols, dict) or not symbols:
        raise ValueError("broker symbol map must be a nonempty JSON object")
    aliases = validate_symbol_map(symbols)
    if not output_path.parent.is_dir():
        raise ValueError("swap snapshot output parent directory must already exist")
    return aliases


def capture_swap_snapshot(
    *,
    client: Any,
    symbol_map_path: Path,
    output_path: Path,
    mt5_server_time: str,
    clock: Clock | None = None,
) -> dict[str, Any]:
    aliases = prepare_swap_capture(symbol_map_path=symbol_map_path, output_path=output_path, mt5_server_time=mt5_server_time)
    # A package whose enum numbers differ would mislabel every mode: refuse before connecting.
    check_mt5_enum_constants(client)
    initialized = False
    try:
        try:
            connected = client.initialize()
        except Exception:
            # The terminal's message may name accounts, servers or paths.
            raise RuntimeError("read-only terminal connection unavailable") from None
        if connected is not True:
            raise RuntimeError("read-only terminal connection unavailable")
        initialized = True
        payload = build_swap_snapshot(client=client, symbols=aliases, captured_at_utc=resolve_clock(clock).now_utc(),
                                      mt5_server_time=mt5_server_time)
        write_swap_snapshot(payload, output_path)
        unavailable = {canonical: record["reason"] for canonical, record in payload["instruments"].items()
                       if record["status"] != "CAPTURED"}
        return SafetyEnvelope().seal({
            "mode": MODE,
            "status": payload["status"],
            "instrument_count": payload["instrument_count"],
            "captured_count": payload["captured_count"],
            "unavailable_count": payload["unavailable_count"],
            "unavailable": unavailable,
            "payload_sha256": payload["payload_sha256"],
            "swap_terms_hash": payload["swap_terms_hash"],
            "captured_at_utc": payload["captured_at_utc"],
            "mt5_server_time": payload["mt5_server_time"],
            "enum_constants_checked": payload["enum_constants_checked"],
            "account_data_read": False,
            "output": str(output_path),
        }, full=True)
    finally:
        if initialized:
            client.shutdown()
