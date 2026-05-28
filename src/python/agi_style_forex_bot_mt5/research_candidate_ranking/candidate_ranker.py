"""Candidate scoring and classification for offline research ranking."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from .blocker_feature_extractor import blocker_features
from .paper_performance_features import paper_performance_features
from .regime_context_features import regime_context_features
from .signal_quality_features import signal_quality_features


def rank_candidates(
    *,
    events: Iterable[Mapping[str, Any]],
    paper_trades: Iterable[Mapping[str, Any]],
    group_key: str,
) -> list[dict[str, Any]]:
    """Rank candidates by symbol or strategy without side effects."""

    grouped_events: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    grouped_trades: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        key = str(event.get(group_key) or "UNKNOWN")
        grouped_events[key].append(event)
    trade_key = "strategy_name" if group_key == "strategy_name" else group_key
    for trade in paper_trades:
        key = str(trade.get(trade_key) or "UNKNOWN")
        grouped_trades[key].append(trade)
    keys = sorted(set(grouped_events) | set(grouped_trades))
    rows = []
    for key in keys:
        ev = grouped_events.get(key, [])
        trades = grouped_trades.get(key, [])
        quality = signal_quality_features(ev)
        blockers = blocker_features(ev)
        context = regime_context_features(ev)
        performance = paper_performance_features(trades)
        scores = _scores(quality, context, performance, blockers)
        classification = _classification(quality, performance, scores)
        rows.append(
            {
                group_key: key,
                **quality,
                **blockers,
                **context,
                **performance,
                **scores,
                "candidate_classification": classification,
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
    return sorted(rows, key=lambda row: float(row.get("final_candidate_score", 0.0)), reverse=True)


def research_recommendations(symbol_rows: list[Mapping[str, Any]], strategy_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    best_symbols = [str(row.get("symbol")) for row in symbol_rows if row.get("candidate_classification") in {"RESEARCH_READY", "NEEDS_MORE_FORWARD_DATA"}][:3]
    pause_symbols = [str(row.get("symbol")) for row in symbol_rows if row.get("candidate_classification") in {"RISK_UNSTABLE", "DO_NOT_PROMOTE", "HIGH_REJECTION_RATE"}]
    watch = [str(row.get("strategy_name")) for row in strategy_rows if row.get("candidate_classification") in {"RESEARCH_READY", "NEEDS_MORE_FORWARD_DATA"}][:5]
    disable = [str(row.get("strategy_name")) for row in strategy_rows if row.get("candidate_classification") in {"RISK_UNSTABLE", "DO_NOT_PROMOTE", "POOR_SIGNAL_QUALITY"}]
    if not symbol_rows and not strategy_rows:
        action = "Collect more forward evidence before ranking candidates."
    elif best_symbols or watch:
        action = "Use ranking as research guidance only; wait for cooldown and normal gates before any paper/shadow observation."
    else:
        action = "Keep research offline and inspect blockers before selecting another shadow window."
    return {
        "best_symbols_for_next_shadow_window": best_symbols,
        "symbols_to_pause_from_research": pause_symbols,
        "strategies_to_watch": watch,
        "strategies_to_disable_candidate": disable,
        "recommended_next_research_action": action,
        "execution_attempted": False,
    }


def _scores(quality: Mapping[str, Any], context: Mapping[str, Any], performance: Mapping[str, Any], blockers: Mapping[str, Any]) -> dict[str, float]:
    rejection_rate = float(quality.get("rejection_rate", 0.0) or 0.0)
    stability = max(0.0, min(100.0, 70.0 + float(performance.get("expectancy_paper", 0.0) or 0.0) * 10.0 + min(15.0, float(performance.get("paper_closed_trades", 0) or 0) * 1.5) - abs(min(0.0, float(performance.get("max_scaled_drawdown", 0.0) or 0.0))) * 8.0))
    readiness = max(0.0, min(100.0, 100.0 - rejection_rate * 0.45 + min(20.0, float(quality.get("signals_detected", 0) or 0) * 1.5)))
    blocker_penalty = min(35.0, float(blockers.get("spread_rejection_count", 0) or 0) * 2.0 + float(blockers.get("stale_signal_count", 0) or 0) * 1.5)
    final = (
        float(quality.get("signal_quality_score", 0.0) or 0.0) * 0.30
        + float(performance.get("paper_performance_score", 0.0) or 0.0) * 0.25
        + stability * 0.20
        + float(context.get("data_quality_score", 0.0) or 0.0) * 0.15
        + readiness * 0.10
        - blocker_penalty
    )
    return {
        "stability_score": max(0.0, min(100.0, stability)),
        "readiness_score": max(0.0, min(100.0, readiness)),
        "final_candidate_score": max(0.0, min(100.0, final)),
    }


def _classification(quality: Mapping[str, Any], performance: Mapping[str, Any], scores: Mapping[str, Any]) -> str:
    signals = int(quality.get("signals_detected", 0) or 0)
    closed = int(performance.get("paper_closed_trades", 0) or 0)
    rejection = float(quality.get("rejection_rate", 0.0) or 0.0)
    final = float(scores.get("final_candidate_score", 0.0) or 0.0)
    if signals == 0 and closed == 0:
        return "DATA_INSUFFICIENT"
    if rejection >= 80.0 and signals >= 3:
        return "HIGH_REJECTION_RATE"
    if float(quality.get("signal_quality_score", 0.0) or 0.0) < 30.0:
        return "POOR_SIGNAL_QUALITY"
    if float(performance.get("max_scaled_drawdown", 0.0) or 0.0) <= -3.0 or (closed >= 3 and float(performance.get("expectancy_paper", 0.0) or 0.0) < 0):
        return "RISK_UNSTABLE"
    if final < 20.0:
        return "DO_NOT_PROMOTE"
    if signals < 10 or closed < 10:
        return "NEEDS_MORE_FORWARD_DATA"
    return "RESEARCH_READY" if final >= 60.0 else "NEEDS_MORE_FORWARD_DATA"
