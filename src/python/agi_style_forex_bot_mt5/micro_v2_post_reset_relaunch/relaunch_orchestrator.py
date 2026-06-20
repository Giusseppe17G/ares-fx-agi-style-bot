"""Read-only input loader for the Micro V2 post-reset relaunch orchestrator."""

from __future__ import annotations

import configparser
import json
import sqlite3
from pathlib import Path
from typing import Any


def load_relaunch_context(
    *,
    v2_sqlite: str | Path,
    v2_log_dir: str | Path,
    reports_root: str | Path,
    v2_profile_config: str | Path,
    daily_risk_ledger: str | Path,
    post_reset_relaunch_dir: str | Path,
) -> dict[str, Any]:
    root = Path(reports_root)
    sqlite_path = Path(v2_sqlite)
    return {
        "paths": {
            "v2_sqlite": str(sqlite_path),
            "v2_log_dir": str(v2_log_dir),
            "reports_root": str(root),
            "v2_profile_config": str(v2_profile_config),
            "daily_risk_ledger": str(daily_risk_ledger),
            "post_reset_relaunch_dir": str(post_reset_relaunch_dir),
        },
        "sqlite_state": _read_sqlite_state(sqlite_path),
        "profile_config": _read_profile_config(Path(v2_profile_config)),
        "daily_risk_ledger": _load_json(Path(daily_risk_ledger)),
        "reset_watcher": _load_json(root / "micro_v2_reset_watcher" / "micro_v2_reset_watcher_summary.json"),
        "post_reset_pack": _load_json(Path(post_reset_relaunch_dir) / "micro_v2_post_reset_relaunch_pack_summary.json"),
        "pre_relaunch_safety": _load_json(root / "micro_v2_pre_relaunch_safety_pack" / "micro_v2_pre_relaunch_safety_pack_summary.json"),
        "daily_risk_scope_repair": _load_json(root / "micro_v2_daily_risk_scope_repair" / "micro_v2_daily_risk_scope_repair_summary.json"),
        "clearance_runtime": _load_json(root / "micro_v2_clearance_runtime_check" / "micro_v2_clearance_runtime_check_summary.json"),
        "market_open_readiness": _load_json(root / "micro_v2_market_open_readiness" / "micro_v2_market_open_readiness_summary.json"),
        "telemetry_status": _load_json(root / "telemetry_repair" / "telemetry_status_summary.json"),
        "execution_evidence": _load_json(root / "execution_evidence" / "execution_evidence_summary.json"),
        "rejection_labeling": _load_json(root / "rejection_labeling_audit" / "rejection_labeling_summary.json"),
        "symbol_rejection": _load_json(root / "micro_v2_symbol_rejection_audit" / "micro_v2_symbol_rejection_summary.json"),
        "paper_risk_status": _load_json(root / "paper_risk" / "paper_risk_status.json"),
        "forward_evidence": _load_json(root / "forward_evidence" / "evidence_summary.json"),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _read_sqlite_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sqlite_exists": False, "open_trade_count": 0, "invalid_open_trade_count": 0, "latest_heartbeat": {}, "runtime": {}}
    state: dict[str, Any] = {"sqlite_exists": True, "open_trade_count": 0, "invalid_open_trade_count": 0, "latest_heartbeat": {}, "runtime": {}}
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as con:
            con.row_factory = sqlite3.Row
            state["open_trade_count"] = _count_open_trades(con)
            state["invalid_open_trade_count"] = _count_invalid_open_trades(con)
            state["latest_heartbeat"] = _latest_heartbeat(con)
            state["runtime"] = _runtime_state(con)
    except Exception as exc:
        state["sqlite_read_error"] = str(exc)
    return state


def _count_open_trades(con: sqlite3.Connection) -> int:
    try:
        row = con.execute("select count(*) as count from paper_trades where lower(coalesce(status, '')) in ('open','active')").fetchone()
        return int(row["count"] or 0)
    except Exception:
        return 0


def _count_invalid_open_trades(con: sqlite3.Connection) -> int:
    try:
        rows = con.execute("select payload_json from paper_trades where lower(coalesce(status, '')) in ('open','active')").fetchall()
    except Exception:
        return 0
    invalid = 0
    for row in rows:
        payload = _json_loads(row["payload_json"])
        entry = _as_float(payload.get("entry_price"))
        sl = _as_float(payload.get("sl_price") or payload.get("stop_loss"))
        if entry is None or sl is None or abs(entry - sl) <= 1e-12:
            invalid += 1
    return invalid


def _latest_heartbeat(con: sqlite3.Connection) -> dict[str, Any]:
    try:
        row = con.execute("select timestamp_utc, mt5_connected, execution_attempted, payload_json from heartbeats order by timestamp_utc desc limit 1").fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    payload = _json_loads(row["payload_json"])
    return {
        "timestamp_utc": row["timestamp_utc"],
        "mt5_connected": bool(row["mt5_connected"]),
        "execution_attempted": bool(row["execution_attempted"]),
        "payload": payload,
    }


def _runtime_state(con: sqlite3.Connection) -> dict[str, Any]:
    try:
        row = con.execute("select payload_json, updated_at_utc from operational_state where state_key='runtime'").fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    payload = _json_loads(row["payload_json"])
    payload["updated_at_utc"] = row["updated_at_utc"]
    return payload


def _read_profile_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"profile_config_exists": False}
    raw = path.read_text(encoding="utf-8", errors="replace")
    parser = configparser.ConfigParser()
    try:
        parser.read_string("[profile]\n" + raw)
        values = {key.upper(): value for key, value in parser["profile"].items()}
    except Exception as exc:
        return {"profile_config_exists": True, "profile_config_parse_error": str(exc), "raw": raw}
    values["profile_config_exists"] = True
    return values


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        return {"_load_error": str(exc)}


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
