"""Read-only loader for post-repair V2 resume guard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset


def load_post_repair_inputs(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    base_sqlite: str | Path,
    base_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
    repair_dir: str | Path,
    lifecycle_dir: str | Path,
    daily_risk_ledger: str | Path | None,
) -> dict[str, Any]:
    return {
        "v2_dataset": load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2"),
        "base_dataset": load_dry_run_dataset(sqlite_path=base_sqlite, log_dir=base_log_dir, label="base"),
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "profile_values": _read_ini_like(Path(v2_profile_config)),
        "repair_summary": _load_json(Path(repair_dir) / "micro_v2_guarded_paper_state_repair_summary.json"),
        "repair_after": _load_json(Path(repair_dir) / "repair_after_snapshot.json"),
        "lifecycle_summary": _load_json(Path(lifecycle_dir) / "micro_v2_lifecycle_risk_comparison_summary.json"),
        "daily_risk_ledger": str(daily_risk_ledger or ""),
        "daily_risk_ledger_payload": _load_json(Path(daily_risk_ledger)) if daily_risk_ledger else {},
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


def _read_ini_like(path: Path) -> dict[str, str]:
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
