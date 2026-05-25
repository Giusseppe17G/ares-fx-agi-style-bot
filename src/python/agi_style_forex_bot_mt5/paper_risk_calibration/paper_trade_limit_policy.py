"""Paper-only trade limit policy for safer forward-shadow profiles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime
from agi_style_forex_bot_mt5.paper_risk_review.profile_matching import read_profile_config_profile

from .paper_risk_budget import micro_risk_budget


@dataclass(frozen=True)
class PaperRiskLimits:
    profile: str = "BALANCED_STABLE_MICRO"
    paper_risk_multiplier: float = 0.10
    max_open_paper_trades: int = 1
    max_paper_trades_per_day: int = 2
    cooldown_after_loss_minutes: int = 120
    cooldown_after_drawdown_halt_minutes: int = 1440
    block_new_entries_after_daily_halt: bool = True
    manual_resume_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "paper_risk_multiplier": self.paper_risk_multiplier,
            "max_open_paper_trades": self.max_open_paper_trades,
            "max_paper_trades_per_day": self.max_paper_trades_per_day,
            "cooldown_after_loss_minutes": self.cooldown_after_loss_minutes,
            "cooldown_after_drawdown_halt_minutes": self.cooldown_after_drawdown_halt_minutes,
            "block_new_entries_after_daily_halt": self.block_new_entries_after_daily_halt,
            "manual_resume_required": self.manual_resume_required,
        }


def load_paper_risk_limits(profile_config: str | Path | None = None) -> PaperRiskLimits:
    """Load paper risk limits from a micro profile INI, falling back to safe defaults."""

    budget = micro_risk_budget()
    values = _read_simple_ini(Path(profile_config)) if profile_config else {}
    profile_info = read_profile_config_profile(profile_config)
    return PaperRiskLimits(
        profile=str(profile_info.get("canonical_profile") or values.get("SIGNAL_PROFILE") or budget["profile"]).upper(),
        paper_risk_multiplier=max(0.0, min(1.0, _float(values.get("PAPER_RISK_MULTIPLIER"), budget["paper_risk_multiplier"]))),
        max_open_paper_trades=max(0, _int(values.get("MAX_OPEN_PAPER_TRADES"), budget["max_open_paper_trades"])),
        max_paper_trades_per_day=max(0, _int(values.get("MAX_PAPER_TRADES_PER_DAY"), budget["max_paper_trades_per_day"])),
        cooldown_after_loss_minutes=max(0, _int(values.get("COOLDOWN_AFTER_LOSS_MINUTES"), budget["cooldown_after_loss_minutes"])),
        cooldown_after_drawdown_halt_minutes=max(0, _int(values.get("COOLDOWN_AFTER_DRAWDOWN_HALT_MINUTES"), budget["cooldown_after_drawdown_halt_minutes"])),
        block_new_entries_after_daily_halt=_bool(values.get("BLOCK_NEW_ENTRIES_AFTER_DAILY_HALT"), budget["block_new_entries_after_daily_halt"]),
        manual_resume_required=_bool(values.get("MANUAL_RESUME_REQUIRED"), budget["manual_resume_required"]),
    )


def evaluate_paper_trade_limits(
    *,
    database: TelemetryDatabase,
    profile_config: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return whether a new paper trade may be opened under paper-only limits."""

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    limits = load_paper_risk_limits(profile_config)
    trades = [_payload(row) for row in database.fetch_paper_trades()]
    open_trades = [trade for trade in trades if str(trade.get("status", "")).upper() == "OPEN"]
    today = now_utc.date().isoformat()
    trades_today = [trade for trade in trades if _trade_open_date(trade) == today]
    state = database.get_operational_state()
    alerts = [_payload(row) for row in database.fetch_all("alerts")]
    drawdown_halts = [alert for alert in alerts if str(alert.get("alert_code") or alert.get("halt_reason") or "").upper() in {"PAPER_DAILY_DRAWDOWN", "PAPER_DAILY_DRAWDOWN_HALT"}]
    paused_reason = str(state.get("paused_reason") or state.get("halt_reason") or "").upper()
    latest_loss = _latest_closed_loss(trades)
    latest_halt_at = _latest_time([*drawdown_halts, state], ("timestamp_utc", "paused_at_utc", "updated_at_utc"))

    result = {
        "paper_risk_status": "PAPER_RISK_OK",
        "paper_risk_profile": limits.profile,
        "current_open_paper_trades": len(open_trades),
        "paper_trades_today": len(trades_today),
        "daily_drawdown_status": "HALTED" if "PAPER_DAILY_DRAWDOWN" in paused_reason or drawdown_halts else "OK",
        "cooldown_active": False,
        "cooldown_until_utc": "",
        "can_open_new_paper_trade": True,
        "blocking_reason": "",
        "limits": limits.to_dict(),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    if len(open_trades) >= limits.max_open_paper_trades:
        return _blocked(result, "PAPER_MAX_OPEN_TRADES_BLOCK")
    if len(trades_today) >= limits.max_paper_trades_per_day:
        return _blocked(result, "PAPER_DAILY_TRADE_LIMIT_BLOCK")
    if limits.block_new_entries_after_daily_halt and ("PAPER_DAILY_DRAWDOWN" in paused_reason or drawdown_halts):
        if limits.manual_resume_required and bool(state.get("shadow_paused", False)):
            return _blocked(result, "PAPER_DRAWDOWN_HALT_BLOCK")
    if latest_loss is not None and limits.cooldown_after_loss_minutes > 0:
        until = latest_loss + timedelta(minutes=limits.cooldown_after_loss_minutes)
        if now_utc < until:
            result["cooldown_active"] = True
            result["cooldown_until_utc"] = until.isoformat()
            return _blocked(result, "PAPER_COOLDOWN_BLOCK")
    if latest_halt_at is not None and limits.cooldown_after_drawdown_halt_minutes > 0:
        until = latest_halt_at + timedelta(minutes=limits.cooldown_after_drawdown_halt_minutes)
        if now_utc < until:
            result["cooldown_active"] = True
            result["cooldown_until_utc"] = until.isoformat()
            return _blocked(result, "PAPER_COOLDOWN_BLOCK")
    return result


def _blocked(result: dict[str, Any], reason: str) -> dict[str, Any]:
    result.update(
        {
            "paper_risk_status": "PAPER_RISK_BLOCKED",
            "can_open_new_paper_trade": False,
            "blocking_reason": reason,
        }
    )
    return result


def _latest_closed_loss(trades: list[Mapping[str, Any]]) -> datetime | None:
    from agi_style_forex_bot_mt5.paper_trading.paper_pnl_engine import pnl_value

    latest: datetime | None = None
    for trade in trades:
        if str(trade.get("status", "")).upper() != "CLOSED":
            continue
        if pnl_value(trade) >= 0:
            continue
        parsed = safe_parse_datetime(trade.get("exit_time_utc") or trade.get("closed_at_utc"), field_name="exit_time_utc", source="paper_risk")
        if parsed.value is not None and (latest is None or parsed.value > latest):
            latest = parsed.value
    return latest


def _latest_time(items: list[Mapping[str, Any]], fields: tuple[str, ...]) -> datetime | None:
    latest: datetime | None = None
    for item in items:
        for field in fields:
            parsed = safe_parse_datetime(item.get(field), field_name=field, source="paper_risk")
            if parsed.value is not None and (latest is None or parsed.value > latest):
                latest = parsed.value
    return latest


def _trade_open_date(trade: Mapping[str, Any]) -> str:
    parsed = safe_parse_datetime(trade.get("entry_time_utc") or trade.get("opened_at_utc"), field_name="entry_time_utc", source="paper_risk")
    return parsed.value.date().isoformat() if parsed.value is not None else str(trade.get("entry_time_utc") or "")[:10]


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


def _read_simple_ini(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def _bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
