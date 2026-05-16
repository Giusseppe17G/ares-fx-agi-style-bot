"""Research objective functions with anti-overfit penalties."""

from __future__ import annotations

from typing import Any, Mapping


def expectancy_r(metrics: Mapping[str, Any]) -> float:
    return float(metrics.get("expectancy_r", metrics.get("average_r", 0.0)) or 0.0)


def profit_factor(metrics: Mapping[str, Any]) -> float:
    value = metrics.get("profit_factor", 0.0)
    return 10.0 if value == "Infinity" else float(value or 0.0)


def return_to_drawdown(metrics: Mapping[str, Any]) -> float:
    dd = abs(float(metrics.get("max_drawdown_pct", 0.0) or 0.0))
    return float(metrics.get("net_return_pct", 0.0) or 0.0) / max(dd, 1.0)


def sharpe_adjusted(metrics: Mapping[str, Any]) -> float:
    sharpe = float(metrics.get("sharpe", 0.0) or 0.0)
    dd = abs(float(metrics.get("max_drawdown_pct", 0.0) or 0.0))
    return sharpe - dd / 50.0


def robustness_score(metrics: Mapping[str, Any]) -> float:
    return max(0.0, 100.0 + expectancy_r(metrics) * 50.0 - abs(float(metrics.get("max_drawdown_pct", 0.0) or 0.0)) * 2.0)


def competitive_score(metrics: Mapping[str, Any]) -> float:
    return float(metrics.get("robustness_score", 0.0) or 0.0) + float(metrics.get("baselines_beaten", 0.0) or 0.0) * 5.0


def composite_score(metrics: Mapping[str, Any]) -> float:
    """Composite objective that penalizes fragile or overfit evidence."""

    trades = int(metrics.get("trades_total", metrics.get("total_trades", metrics.get("trades_count", 0))) or 0)
    pf = profit_factor(metrics)
    dd = abs(float(metrics.get("max_drawdown_pct", 0.0) or 0.0))
    score = 50.0
    score += expectancy_r(metrics) * 35.0
    score += min(pf, 3.0) * 8.0
    score += return_to_drawdown(metrics) * 4.0
    if trades < 300:
        score -= (300 - trades) / 300.0 * 30.0
    if dd > 12:
        score -= min(35.0, (dd - 12) * 2.0)
    if pf > 3.0 and trades < 100:
        score -= 20.0
    if float(metrics.get("top_5_profit_concentration_pct", 0.0) or 0.0) > 40.0:
        score -= 18.0
    if float(metrics.get("oos_expectancy_r", 0.0) or 0.0) < 0:
        score -= 25.0
    if float(metrics.get("cost_sensitivity_loss_pct", 0.0) or 0.0) > 50.0:
        score -= 18.0
    if float(metrics.get("session_concentration_pct", 0.0) or 0.0) > 70.0:
        score -= 12.0
    if float(metrics.get("regime_concentration_pct", 0.0) or 0.0) > 70.0:
        score -= 12.0
    if float(metrics.get("top_5_removed_profit_pct", 0.0) or 0.0) < 0:
        score -= 18.0
    return max(0.0, min(100.0, score))
