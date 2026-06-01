"""Read-only inputs for Micro V2 lifecycle/risk comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset


def load_lifecycle_inputs(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    base_sqlite: str | Path,
    base_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
    stable_window_dir: str | Path,
    checkpoint_dir: str | Path,
    filter_analysis_dir: str | Path,
    consolidated_dir: str | Path,
) -> dict[str, Any]:
    return {
        "v2_dataset": load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2"),
        "base_dataset": load_dry_run_dataset(sqlite_path=base_sqlite, log_dir=base_log_dir, label="base"),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "profile_values": read_ini_like(Path(v2_profile_config)),
        "stable_window": _load_json(Path(stable_window_dir) / "micro_v2_stable_market_window_summary.json"),
        "checkpoint": _load_json(Path(checkpoint_dir) / "micro_v2_observation_checkpoint_summary.json"),
        "filter_analysis": _load_json(Path(filter_analysis_dir) / "micro_v2_filter_analysis_summary.json"),
        "consolidated": _load_json(Path(consolidated_dir) / "micro_v2_consolidated_audit_summary.json"),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def read_ini_like(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
