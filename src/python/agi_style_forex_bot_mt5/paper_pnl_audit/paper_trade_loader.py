"""Load paper trade and drawdown evidence without mutating it."""

from __future__ import annotations

import json
import configparser
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


HALT_CODES = {"PAPER_DAILY_DRAWDOWN", "PAPER_DAILY_DRAWDOWN_HALT", "PAPER_SHADOW_HALTED"}


def load_paper_trade_evidence(
    *,
    database: TelemetryDatabase,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    reports_root: str | Path = "data/reports",
    paper_risk_dir: str | Path = "data/reports/paper_risk",
    daily_risk_dir: str | Path = "data/reports/paper_daily_risk",
    profile_config: str | Path | None = None,
) -> dict[str, Any]:
    profile_defaults = _profile_defaults(profile_config)
    trades = [_trade_row(_payload(row), "sqlite", profile_defaults) for row in database.fetch_paper_trades()]
    alerts = [_payload(row) for row in database.fetch_all("alerts")]
    logs = _load_jsonl(Path(log_dir))
    paper_state = _load_json(Path(reports_root) / "paper_state" / "paper_state_report.json")
    paper_risk = _load_json(Path(paper_risk_dir) / "paper_risk_summary.json")
    daily_risk = _load_json(Path(daily_risk_dir) / "paper_daily_risk_summary.json")
    halts = [
        item
        for item in [*alerts, *logs]
        if str(item.get("alert_code") or item.get("event_type") or item.get("halt_reason") or "").upper() in HALT_CODES
    ]
    return {
        "trades": trades,
        "halts": halts,
        "paper_state": paper_state,
        "paper_risk_summary": paper_risk,
        "daily_risk_summary": daily_risk,
        "profile_defaults": profile_defaults,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _trade_row(trade: Mapping[str, Any], source: str, profile_defaults: Mapping[str, Any] | None = None) -> dict[str, Any]:
    metadata = trade.get("metadata") if isinstance(trade.get("metadata"), Mapping) else {}
    defaults = profile_defaults or {}
    paper_multiplier = _float(metadata.get("paper_risk_multiplier") or trade.get("paper_risk_multiplier") or defaults.get("paper_risk_multiplier"), 1.0)
    risk_multiplier = _float(metadata.get("risk_multiplier") or metadata.get("paper_risk_multiplier") or trade.get("risk_multiplier") or defaults.get("risk_multiplier") or paper_multiplier, 1.0)
    return {
        "trade_id": trade.get("paper_trade_id") or trade.get("trade_id") or "",
        "symbol": str(trade.get("symbol") or "").upper(),
        "strategy_name": trade.get("strategy_name", ""),
        "entry_time_utc": trade.get("entry_time_utc") or trade.get("opened_at_utc"),
        "exit_time_utc": trade.get("exit_time_utc") or trade.get("closed_at_utc"),
        "entry_price": _float(trade.get("entry_price")),
        "exit_price": _float(trade.get("exit_price") or trade.get("current_price")),
        "current_price": _float(trade.get("current_price")),
        "stop_loss": _float(trade.get("sl_price") or trade.get("stop_loss")),
        "take_profit": _float(trade.get("tp_price") or trade.get("take_profit")),
        "direction": str(trade.get("direction") or "").upper(),
        "volume": _float(trade.get("lot") or trade.get("volume") or trade.get("paper_size")),
        "risk_multiplier": risk_multiplier,
        "paper_risk_multiplier": paper_multiplier,
        "profile": str(metadata.get("profile") or metadata.get("signal_profile_used") or trade.get("profile") or ""),
        "reported_profit": _float(trade.get("profit")),
        "raw_pnl": _float(trade.get("raw_pnl"), _float(trade.get("profit"))),
        "scaled_paper_pnl": _float(trade.get("scaled_paper_pnl")) if trade.get("scaled_paper_pnl") is not None else None,
        "multiplier_applied": bool(trade.get("multiplier_applied") or metadata.get("multiplier_applied", False)),
        "pnl_scaling_status": str(trade.get("pnl_scaling_status") or metadata.get("pnl_scaling_status") or ""),
        "pnl_formula_version": str(trade.get("pnl_formula_version") or metadata.get("pnl_formula_version") or ""),
        "reported_r_multiple": _float(trade.get("r_multiple")),
        "risk_amount": _float(trade.get("risk_amount")),
        "risk_pct": _float(trade.get("risk_pct")),
        "spread_points": _float(trade.get("spread_at_entry")),
        "commission_assumed": _float(trade.get("commission_assumed")),
        "metadata": dict(metadata),
        "profile_defaults": dict(defaults),
        "source": source,
        "execution_attempted": False,
    }


def _profile_defaults(profile_config: str | Path | None) -> dict[str, Any]:
    if profile_config is None:
        return {}
    path = Path(profile_config)
    if not path.exists():
        return {}
    parser = configparser.ConfigParser()
    parser.optionxform = str
    text = path.read_text(encoding="utf-8", errors="ignore")
    parser.read_string("[profile]\n" + text)
    section = parser["profile"]
    multiplier = section.get("PAPER_RISK_MULTIPLIER") or section.get("paper_risk_multiplier") or "1.0"
    return {
        "profile": section.get("SIGNAL_PROFILE") or section.get("profile") or section.get("PROFILE") or ("BALANCED_STABLE_MICRO" if "balanced_stable_micro" in path.name.lower() else ""),
        "paper_risk_multiplier": _float(multiplier, 1.0),
        "risk_multiplier": _float(section.get("RISK_MULTIPLIER") or multiplier, 1.0),
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_jsonl(log_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not log_dir.exists():
        return rows
    for path in log_dir.glob("*.jsonl"):
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip():
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        rows.append(payload)
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def _payload(row: Any) -> dict[str, Any]:
    try:
        if "payload_json" in row.keys():
            return json.loads(row["payload_json"])
    except Exception:
        pass
    try:
        return dict(row)
    except Exception:
        return {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
