"""Read-only input loading for Micro V2 observation checkpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset


def load_checkpoint_inputs(
    *,
    base_sqlite: str | Path,
    base_log_dir: str | Path,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
) -> dict[str, Any]:
    reports = Path(reports_root)
    return {
        "base_dataset": load_dry_run_dataset(sqlite_path=base_sqlite, log_dir=base_log_dir, label="base"),
        "v2_dataset": load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2"),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "existing_readiness": _load_json(reports / "micro_v2_market_open_readiness" / "micro_v2_market_open_readiness_summary.json"),
        "existing_monitor": _load_json(reports / "micro_v2_dry_run_monitor" / "micro_v2_dry_run_monitor_summary.json"),
        "existing_rejection": _load_json(reports / "rejection_labeling_audit" / "rejection_labeling_summary.json"),
        "existing_acceptance": _load_json(reports / "micro_v2_dry_run" / "forward_evidence" / "operational_acceptance.json"),
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
