"""Read-only input loader for Micro V2 market-open readiness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset
from agi_style_forex_bot_mt5.micro_v2_symbol_rejection_audit.symbol_rejection_loader import load_ini


def load_market_open_inputs(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
    rejection_labeling_dir: str | Path,
    monitor_dir: str | Path,
) -> dict[str, Any]:
    return {
        "dataset": load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2"),
        "profile": load_ini(v2_profile_config),
        "profile_path": str(v2_profile_config),
        "rejection_labeling": _load_json(Path(rejection_labeling_dir) / "rejection_labeling_summary.json"),
        "monitor": _load_json(Path(monitor_dir) / "micro_v2_dry_run_monitor_summary.json"),
        "reports_root": str(reports_root),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}
