"""Read-only loading for Micro V2 stable market window audit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset


DEFAULT_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"]


def load_stable_window_inputs(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    base_sqlite: str | Path,
    base_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
    checkpoint_dir: str | Path,
    readiness_dir: str | Path,
    filter_analysis_dir: str | Path,
    consolidated_dir: str | Path,
) -> dict[str, Any]:
    return {
        "v2_dataset": load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2"),
        "base_dataset": load_dry_run_dataset(sqlite_path=base_sqlite, log_dir=base_log_dir, label="base"),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "profile_values": _read_ini_like(Path(v2_profile_config)),
        "checkpoint": _load_json(Path(checkpoint_dir) / "micro_v2_observation_checkpoint_summary.json"),
        "readiness": _load_json(Path(readiness_dir) / "micro_v2_market_open_readiness_summary.json"),
        "filter_analysis": _load_json(Path(filter_analysis_dir) / "micro_v2_filter_analysis_summary.json"),
        "consolidated": _load_json(Path(consolidated_dir) / "micro_v2_consolidated_audit_summary.json"),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def configured_symbols(profile_values: dict[str, str]) -> list[str]:
    for key in ("SYMBOLS", "ALLOWED_SYMBOLS", "SYMBOL_UNIVERSE", "ENABLED_SYMBOLS"):
        raw = profile_values.get(key, "")
        if raw:
            symbols = [item.strip().upper() for item in raw.split(",") if item.strip()]
            if symbols:
                return symbols
    return list(DEFAULT_SYMBOLS)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _read_ini_like(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "[")) or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values
