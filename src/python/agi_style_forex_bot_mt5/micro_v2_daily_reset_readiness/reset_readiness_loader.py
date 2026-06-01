"""Read-only inputs for Micro V2 daily reset readiness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset


def load_reset_readiness_inputs(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
    daily_risk_ledger: str | Path,
    daily_risk_scope_repair_dir: str | Path,
    closed_loss_scope_dir: str | Path,
) -> dict[str, Any]:
    dataset = load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2")
    return {
        "dataset": dataset,
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "daily_risk_ledger": str(daily_risk_ledger),
        "ledger_payload": _load_json(Path(daily_risk_ledger)),
        "daily_risk_scope_repair_summary": _load_json(Path(daily_risk_scope_repair_dir) / "micro_v2_daily_risk_scope_repair_summary.json"),
        "closed_loss_summary": _load_json(Path(closed_loss_scope_dir) / "micro_v2_closed_loss_scope_decision_summary.json"),
        "profile_values": _read_ini_like(Path(v2_profile_config)),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def safety_flags(dataset: dict[str, Any]) -> bool:
    for group in ("events", "heartbeats", "paper_trades"):
        for row in dataset.get(group, []):
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if bool(row.get("execution_attempted")) or bool(row.get("order_send_called")) or bool(row.get("order_check_called")):
                return True
            if bool(payload.get("execution_attempted")) or bool(payload.get("order_send_called")) or bool(payload.get("order_check_called")):
                return True
    return False


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
