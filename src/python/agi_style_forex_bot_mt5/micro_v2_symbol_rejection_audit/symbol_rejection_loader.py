"""Load V2 symbol rejection inputs without mutating runtime state."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.micro_v2_dry_run_monitor.dry_run_loader import load_dry_run_dataset


def load_symbol_rejection_inputs(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
    stable_gate: str | Path,
    monitor_dir: str | Path,
) -> dict[str, Any]:
    dataset = load_dry_run_dataset(sqlite_path=v2_sqlite, log_dir=v2_log_dir, label="v2")
    return {
        "dataset": dataset,
        "profile": load_ini(v2_profile_config),
        "profile_path": str(v2_profile_config),
        "stable_gate": _load_json(Path(stable_gate)),
        "stable_gate_path": str(stable_gate),
        "monitor_summary": _load_json(Path(monitor_dir) / "micro_v2_dry_run_monitor_summary.json"),
        "monitor_rejections": _load_csv(Path(monitor_dir) / "v2_rejections.csv"),
        "reports_root": str(reports_root),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def load_ini(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(path)
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def symbol_rejection_events(dataset: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in dataset.get("events", []):
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        event_type = str(event.get("event_type", "")).upper()
        reason = str(payload.get("reject_reason") or payload.get("reason") or event.get("message") or event_type).lower()
        if event_type == "SYMBOL_REJECTED" or reason == "symbol_rejected":
            rows.append(dict(event))
    return rows


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _load_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []
