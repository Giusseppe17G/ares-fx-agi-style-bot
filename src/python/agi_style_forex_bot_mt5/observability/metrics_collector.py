"""Collect forward-shadow operational metrics from SQLite."""

from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.persistence import validate_event_integrity
from agi_style_forex_bot_mt5.core.clock import Clock, resolve_clock
from agi_style_forex_bot_mt5.core.operational_state.errors import PaperStateError
from agi_style_forex_bot_mt5.portfolio import build_portfolio_state
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


class MetricsCollector:
    """Build compact status metrics from telemetry tables."""

    def __init__(self, database: TelemetryDatabase, *, clock: Clock | None = None) -> None:
        self.database = database
        self.clock = resolve_clock(clock)

    def collect(self) -> dict[str, Any]:
        now_utc = self.clock.now_utc().astimezone(timezone.utc)
        trades = [json.loads(row["payload_json"]) for row in self.database.fetch_paper_trades()]
        events = self.database.fetch_all("events")
        predictions = self.database.fetch_all("model_predictions")
        event_counts = Counter(str(row["event_type"]) for row in events)
        rejection_counts = Counter()
        symbols_rejected = 0
        dynamic_risk_reduced = False
        strategy_concentration_high = False
        regime_concentration_high = False
        correlation_cluster_high = False
        for row in events:
            payload = {}
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                payload = {}
            if str(row["event_type"]) in {"SIGNAL_REJECTED", "RISK_REJECTED", "SYMBOL_REJECTED"}:
                reason = payload.get("reject_reason") or payload.get("reject_code") or row["event_type"]
                rejection_counts[str(reason)] += 1
            if str(row["event_type"]) == "SYMBOL_REJECTED":
                symbols_rejected += 1
            if str(row["event_type"]) == "DYNAMIC_RISK_ADJUSTED" and float(payload.get("risk_multiplier") or 1.0) < 1.0:
                dynamic_risk_reduced = True
            if str(row["event_type"]) == "PORTFOLIO_DECISION":
                code = str(payload.get("reject_code") or "")
                strategy_concentration_high = strategy_concentration_high or code == "STRATEGY_CONCENTRATION_HIGH"
                regime_concentration_high = regime_concentration_high or code == "REGIME_CONCENTRATION_HIGH"
                correlation_cluster_high = correlation_cluster_high or code == "CORRELATION_CLUSTER_HIGH"
        metrics = _paper_metrics(trades)
        risk_metrics = _paper_risk_metrics(trades, self.database.get_operational_state(), now_utc)
        open_trades = sum(1 for trade in trades if trade.get("status") == "OPEN")
        closed_today = sum(
            1
            for trade in trades
            if trade.get("status") == "CLOSED"
            and trade.get("exit_time_utc")
            and _closed_on_utc_day(trade.get("exit_time_utc"), now_utc.date().isoformat())
        )
        portfolio_state = build_portfolio_state(self.database).to_dict()
        integrity = validate_event_integrity(database=self.database)
        outbox_pending = sum(1 for row in self.database.fetch_all("telegram_outbox") if row["status"] in {"PENDING", "FAILED"})
        fill_quality_poor = sum(1 for trade in trades if str(trade.get("metadata", {}).get("fill_quality", "")).upper() == "POOR")
        ambiguous_intrabar = sum(1 for trade in trades if trade.get("metadata", {}).get("ambiguity_flags"))
        rejected_by_spread = event_counts.get("SPREAD_MODEL_REJECTED", 0)
        slippage_values = [float(trade.get("slippage_assumed_points") or 0.0) for trade in trades]
        return {
            "mode": "forward-shadow",
            "bot_uptime_seconds": 0,
            "mt5_connected": bool(self.database.get_latest_health().get("mt5_connected", False)),
            "symbols_seen": event_counts.get("SYMBOL_ACCEPTED", 0) + symbols_rejected,
            "symbols_rejected": symbols_rejected,
            "signals_detected": event_counts.get("SIGNAL_DETECTED", 0),
            "signals_rejected": event_counts.get("SIGNAL_REJECTED", 0),
            "rejected_signals_by_reason": dict(rejection_counts),
            "paper_trades_open": open_trades,
            "paper_trades_closed": metrics["closed_trades"],
            "closed_paper_trades_today": closed_today,
            "winrate_paper": metrics["winrate"],
            "expectancy_r_paper": metrics["expectancy_r"],
            # Historical PnL drawdown is money, never a daily percentage.
            "historical_drawdown_amount": metrics["max_drawdown_shadow"],
            **risk_metrics,
            "profit_factor_paper": metrics["profit_factor"],
            "critical_errors_recent": event_counts.get("CRITICAL_ERROR", 0)
            + event_counts.get("FORWARD_SHADOW_CRITICAL_ERROR", 0),
            "disk_free_gb": _disk_free_gb(),
            "memory_approx_mb": _memory_approx_mb(),
            "ml_predictions_today": len(predictions),
            "ml_rejected_signals_today": _prediction_count(predictions, "ML_REJECTED"),
            "ml_approved_signals_today": _prediction_count(predictions, "ML_APPROVED"),
            "avg_probability_today": _avg_probability(predictions),
            "model_id": _latest_model_id(predictions),
            "model_status": _latest_model_status(predictions),
            "portfolio_risk_pct": portfolio_state["portfolio_risk_pct"],
            "available_risk_budget_pct": portfolio_state["available_risk_budget_pct"],
            "currency_exposure": portfolio_state["currency_exposure"],
            "concentration_flags": portfolio_state["concentration_flags"],
            "currency_exposure_high": "CURRENCY_EXPOSURE_HIGH" in portfolio_state["concentration_flags"],
            "portfolio_risk_budget_low": "PORTFOLIO_RISK_BUDGET_LOW" in portfolio_state["concentration_flags"],
            "correlation_cluster_high": correlation_cluster_high,
            "dynamic_risk_reduced": dynamic_risk_reduced,
            "strategy_concentration_high": strategy_concentration_high,
            "regime_concentration_high": regime_concentration_high,
            "db_health_status": "OK",
            "last_backup_utc": _last_backup_utc(),
            "audit_integrity_status": integrity["status"],
            "telegram_outbox_pending": outbox_pending,
            "event_gap_count": integrity["event_gap_count"],
            "replay_possible": integrity["replay_possible"],
            "fill_quality_poor_count": fill_quality_poor,
            "ambiguous_intrabar_events": ambiguous_intrabar,
            "rejected_by_spread_model": rejected_by_spread,
            "assumed_slippage_avg": (sum(slippage_values) / len(slippage_values)) if slippage_values else 0.0,
            "cost_model_status": "WATCHLIST" if fill_quality_poor or rejected_by_spread else "OK",
            "paper_vs_backtest_status": "NEEDS_MORE_FORWARD_DATA",
            "execution_attempted": False,
        }


def _paper_risk_metrics(trades: list[dict[str, Any]], state: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Read a fresh valuation of this exact book; no equity guesses or DB writes."""

    # paper_trading exports ForwardShadowBot, which imports observability.
    # Defer the domain import until package initialization has completed.
    from agi_style_forex_bot_mt5.paper_trading.decision_state import PAPER_DECISION_STATE_KEY, paper_book_fingerprint

    unknown = {
        "drawdown_paper": None, "paper_drawdown_unit": "percent",
        "daily_drawdown_pct": None, "floating_drawdown_pct": None,
        "paper_balance": None, "paper_equity": None, "paper_realized_pnl": None,
        "paper_floating_pnl": None, "daily_drawdown_halted": None,
        "paper_risk_state_status": "UNKNOWN", "paper_risk_state_reason": "PAPER_RISK_REFERENCE_MISSING",
        "historical_drawdown_currency": "UNKNOWN",
    }
    ledger = state.get(PAPER_DECISION_STATE_KEY)
    if not isinstance(ledger, dict) or ledger.get("schema_version") != "1.0":
        return unknown
    currency = ledger.get("currency")
    if isinstance(currency, str) and len(currency) == 3 and currency.isascii() and currency.isalpha():
        unknown["historical_drawdown_currency"] = currency.upper()
    else:
        return {**unknown, "paper_risk_state_reason": "PAPER_RISK_CURRENCY_UNVERIFIED"}
    valuation = ledger.get("observed_valuation")
    if not isinstance(valuation, dict):
        return {**unknown, "paper_risk_state_reason": "PAPER_MARK_TO_MARKET_MISSING"}
    try:
        if now.utcoffset() is None:
            raise ValueError
        now = now.astimezone(timezone.utc)
        observed = datetime.fromisoformat(valuation["valued_at_utc"])
        if observed.utcoffset() is None or not 0 <= (now - observed).total_seconds() <= 5:
            return {**unknown, "paper_risk_state_reason": "PAPER_MARK_TO_MARKET_STALE"}
        reference = ledger["daily_references"][now.date().isoformat()]
        daily_equity = reference["equity"]
        numbers = (daily_equity, valuation["balance"], valuation["equity"], valuation["realized_pnl"], valuation["floating_pnl"])
        if not all(type(value) in (float, int) and math.isfinite(value) for value in numbers) or daily_equity <= 0:
            raise ValueError
        if type(reference["halted"]) is not bool:
            raise ValueError
        if valuation["trade_state_hash"] != paper_book_fingerprint(trades):
            return {**unknown, "paper_risk_state_reason": "PAPER_BOOK_CHANGED_SINCE_VALUATION"}
        balance, equity = valuation["balance"], valuation["equity"]
        initial_balance = ledger["initial_balance"]
        if type(initial_balance) not in (int, float) or not math.isfinite(initial_balance) or initial_balance <= 0:
            raise ValueError
        if not math.isclose(balance, initial_balance + valuation["realized_pnl"], rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError
        if not math.isclose(equity, balance + valuation["floating_pnl"], rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError
        daily = max(0.0, (daily_equity - equity) / daily_equity * 100)
        floating = max(0.0, (balance - equity) / balance * 100) if balance > 0 else None
        return {
            **unknown, "drawdown_paper": -daily, "daily_drawdown_pct": daily,
            "floating_drawdown_pct": floating, "paper_balance": balance, "paper_equity": equity,
            "paper_realized_pnl": valuation["realized_pnl"], "paper_floating_pnl": valuation["floating_pnl"],
            "daily_drawdown_halted": reference["halted"], "paper_risk_state_status": "VERIFIED",
            "paper_risk_state_reason": "", "paper_risk_valued_at_utc": observed.isoformat(),
        }
    except (KeyError, TypeError, ValueError, OverflowError, PaperStateError):
        return {**unknown, "paper_risk_state_reason": "PAPER_RISK_REFERENCE_INVALID"}


def _closed_on_utc_day(value: Any, day: str) -> bool:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.utcoffset() is not None and stamp.astimezone(timezone.utc).date().isoformat() == day
    except (TypeError, ValueError):
        return False


def _paper_metrics(trades: list[dict[str, Any]]) -> dict[str, float | int]:
    from agi_style_forex_bot_mt5.paper_trading.paper_pnl_engine import pnl_value

    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    wins = [trade for trade in closed if float(trade.get("r_multiple") or 0.0) > 0]
    losses = [trade for trade in closed if float(trade.get("r_multiple") or 0.0) < 0]
    gross_profit = sum(pnl_value(trade) for trade in closed if pnl_value(trade) > 0)
    gross_loss = abs(sum(pnl_value(trade) for trade in closed if pnl_value(trade) < 0))
    r_values = [float(trade.get("r_multiple") or 0.0) for trade in closed]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for trade in closed:
        equity += pnl_value(trade)
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return {
        "closed_trades": len(closed),
        "winrate": (len(wins) / len(closed) * 100.0) if closed else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
        "expectancy_r": (sum(r_values) / len(r_values)) if r_values else 0.0,
        "max_drawdown_shadow": max_dd,
    }


def _disk_free_gb() -> float:
    usage = shutil.disk_usage(".")
    return round(usage.free / (1024**3), 2)


def _memory_approx_mb() -> float | None:
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.ullAvailPhys / (1024**2), 0)
    except Exception:
        return None
    return None


def _prediction_payloads(rows: list[Any]) -> list[dict[str, Any]]:
    payloads = []
    for row in rows:
        try:
            payloads.append(json.loads(row["payload_json"]))
        except Exception:
            continue
    return payloads


def _prediction_count(rows: list[Any], status: str) -> int:
    return sum(1 for payload in _prediction_payloads(rows) if payload.get("ml_status") == status)


def _avg_probability(rows: list[Any]) -> float:
    values = [float(payload["probability_of_success"]) for payload in _prediction_payloads(rows) if payload.get("probability_of_success") is not None]
    return sum(values) / len(values) if values else 0.0


def _latest_model_id(rows: list[Any]) -> str:
    payloads = _prediction_payloads(rows)
    return str(payloads[-1].get("model_id") or "") if payloads else ""


def _latest_model_status(rows: list[Any]) -> str:
    payloads = _prediction_payloads(rows)
    return str(payloads[-1].get("ml_status") or "ML_DISABLED") if payloads else "ML_DISABLED"


def _last_backup_utc() -> str | None:
    backup_dir = Path("data/backups")
    if not backup_dir.exists():
        return None
    files = [path for path in backup_dir.iterdir() if path.is_file()]
    if not files:
        return None
    newest = max(files, key=lambda path: path.stat().st_mtime)
    from datetime import datetime, timezone

    return datetime.fromtimestamp(newest.stat().st_mtime, timezone.utc).isoformat()
