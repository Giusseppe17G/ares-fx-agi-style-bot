"""Read-only loader for Micro V2 closed loss scope decision."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset


def load_closed_loss_scope_inputs(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
    daily_risk_ledger: str | Path | None,
    drawdown_recovery_dir: str | Path,
    open_trade_repair_dir: str | Path,
    schema_repair_dir: str | Path,
) -> dict[str, Any]:
    dataset = load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2")
    return {
        "dataset": dataset,
        "v2_sqlite": str(v2_sqlite),
        "v2_log_dir": str(v2_log_dir),
        "reports_root": str(reports_root),
        "v2_profile_config": str(v2_profile_config),
        "profile_values": _read_ini_like(Path(v2_profile_config)),
        "daily_risk_ledger": str(daily_risk_ledger or ""),
        "daily_risk_ledger_payload": _load_json(Path(daily_risk_ledger)) if daily_risk_ledger else {},
        "drawdown_recovery_summary": _load_json(Path(drawdown_recovery_dir) / "micro_v2_daily_drawdown_state_recovery_summary.json"),
        "open_trade_repair_summary": _load_json(Path(open_trade_repair_dir) / "micro_v2_guarded_open_trade_integrity_repair_summary.json"),
        "schema_repair_summary": _load_json(Path(schema_repair_dir) / "micro_v2_papertrade_schema_repair_summary.json"),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def safety_flags(dataset: Mapping[str, Any]) -> bool:
    for group in ("events", "heartbeats", "paper_trades"):
        for row in dataset.get(group, []):
            payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
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
