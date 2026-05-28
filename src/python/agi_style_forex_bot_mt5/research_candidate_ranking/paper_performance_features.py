"""Paper performance features for offline research ranking."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def paper_performance_features(trades: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(trade) for trade in trades]
    closed = [row for row in rows if str(row.get("status", "")).upper() == "CLOSED"]
    pnl = [_pnl(row) for row in closed]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    expectancy = sum(pnl) / len(pnl) if pnl else 0.0
    drawdown = _drawdown(pnl)
    risk_penalty = min(45.0, abs(min(0.0, drawdown)) * 6.0)
    perf_score = 50.0 + min(25.0, expectancy * 10.0) + min(20.0, len(closed) * 2.0) - risk_penalty
    return {
        "paper_closed_trades": len(closed),
        "paper_winrate": len(wins) / max(1, len(closed)) * 100.0 if closed else 0.0,
        "avg_scaled_pnl": expectancy,
        "max_scaled_drawdown": drawdown,
        "expectancy_paper": expectancy,
        "paper_profit_factor": gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0.0),
        "paper_performance_score": max(0.0, min(100.0, perf_score)),
        "execution_attempted": False,
    }


def _pnl(trade: Mapping[str, Any]) -> float:
    for key in ("scaled_paper_pnl", "scaled_pnl", "profit", "r_multiple"):
        try:
            return float(trade.get(key) or 0.0)
        except Exception:
            continue
    return 0.0


def _drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst
