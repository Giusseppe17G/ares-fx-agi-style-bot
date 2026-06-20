"""Read-only loader for Micro V2 reset watcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_reset_watcher_inputs(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
    daily_risk_ledger: str | Path,
    post_reset_relaunch_dir: str | Path,
    pre_relaunch_safety_dir: str | Path,
    daily_risk_scope_repair_dir: str | Path,
) -> dict[str, Any]:
    return {
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "daily_risk_ledger": str(daily_risk_ledger),
        "post_reset_relaunch": _load_json(Path(post_reset_relaunch_dir) / "micro_v2_post_reset_relaunch_pack_summary.json"),
        "pre_relaunch_safety": _load_json(Path(pre_relaunch_safety_dir) / "micro_v2_pre_relaunch_safety_pack_summary.json"),
        "daily_risk_scope_repair": _load_json(Path(daily_risk_scope_repair_dir) / "micro_v2_daily_risk_scope_repair_summary.json"),
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
