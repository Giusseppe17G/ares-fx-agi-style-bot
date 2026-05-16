"""Collect forward-shadow operational metrics from SQLite."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import date
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


class MetricsCollector:
    """Build compact status metrics from telemetry tables."""

    def __init__(self, database: TelemetryDatabase) -> None:
        self.database = database

    def collect(self) -> dict[str, Any]:
        trades = [json.loads(row["payload_json"]) for row in self.database.fetch_paper_trades()]
        events = self.database.fetch_all("events")
        predictions = self.database.fetch_all("model_predictions")
        event_counts = Counter(str(row["event_type"]) for row in events)
        rejection_counts = Counter()
        symbols_rejected = 0
        for row in events:
            if str(row["event_type"]) in {"SIGNAL_REJECTED", "RISK_REJECTED", "SYMBOL_REJECTED"}:
                try:
                    payload = json.loads(row["payload_json"])
                except json.JSONDecodeError:
                    payload = {}
                reason = payload.get("reject_reason") or payload.get("reject_code") or row["event_type"]
                rejection_counts[str(reason)] += 1
            if str(row["event_type"]) == "SYMBOL_REJECTED":
                symbols_rejected += 1
        metrics = _paper_metrics(trades)
        open_trades = sum(1 for trade in trades if trade.get("status") == "OPEN")
        closed_today = sum(
            1
            for trade in trades
            if trade.get("status") == "CLOSED"
            and trade.get("exit_time_utc")
            and str(trade.get("exit_time_utc"))[:10] == date.today().isoformat()
        )
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
            "drawdown_paper": metrics["max_drawdown_shadow"],
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
            "execution_attempted": False,
        }


def _paper_metrics(trades: list[dict[str, Any]]) -> dict[str, float | int]:
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    wins = [trade for trade in closed if float(trade.get("r_multiple") or 0.0) > 0]
    losses = [trade for trade in closed if float(trade.get("r_multiple") or 0.0) < 0]
    gross_profit = sum(float(trade.get("profit") or 0.0) for trade in closed if float(trade.get("profit") or 0.0) > 0)
    gross_loss = abs(sum(float(trade.get("profit") or 0.0) for trade in closed if float(trade.get("profit") or 0.0) < 0))
    r_values = [float(trade.get("r_multiple") or 0.0) for trade in closed]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for trade in closed:
        equity += float(trade.get("profit") or 0.0)
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
