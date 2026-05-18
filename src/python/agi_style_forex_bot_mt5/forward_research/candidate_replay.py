"""Research-only replay classification for blocked forward candidates."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def replay_candidates(candidates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Reconstruct why candidates were blocked without creating paper trades."""

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        blockers = _as_tuple(candidate.get("blocking_reasons"))
        thresholds = dict(candidate.get("thresholds_used") or {})
        score = _float(candidate.get("ensemble_score"))
        threshold = _float(thresholds.get("ensemble_min_score", 0.0))
        if not candidate.get("symbol") or not candidate.get("strategy_name"):
            decision = "DATA_INCOMPLETE"
            reason = "candidate metadata is incomplete"
        elif any(str(item).startswith("FEATURE_") or str(item).startswith("LIVE_") for item in blockers):
            decision = "FEATURE_INCONSISTENT"
            reason = "candidate depends on feature/runtime data blocker"
        elif any(str(item).startswith("STABLE_") for item in blockers):
            decision = "BLOCK_CORRECT"
            reason = "stable profile filter blocked the candidate"
        elif "REGIME_MISMATCH" in blockers:
            decision = "BLOCK_CORRECT"
            reason = "strategy regime filter rejected the live context"
        elif "ENSEMBLE_SCORE_LOW" in blockers and 0.0 <= threshold - score <= 10.0:
            decision = "BLOCK_TOO_STRICT_RESEARCH_ONLY"
            reason = "ensemble score is close enough for research-only sensitivity"
        elif blockers:
            decision = "BLOCK_CORRECT"
            reason = f"blocked by {blockers[0]}"
        else:
            decision = "NEEDS_MORE_FORWARD_CANDIDATES"
            reason = "no blocking reason found"
        rows.append(
            {
                **dict(candidate),
                "replay_decision": decision,
                "replay_reason": reason,
                "execution_attempted": False,
            }
        )
    return rows


def replay_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows_list = [dict(row) for row in rows]
    counts: dict[str, int] = {}
    blockers: dict[str, int] = {}
    for row in rows_list:
        counts[str(row.get("replay_decision"))] = counts.get(str(row.get("replay_decision")), 0) + 1
        for blocker in _as_tuple(row.get("blocking_reasons")):
            blockers[blocker] = blockers.get(blocker, 0) + 1
    status = "OK" if rows_list else "NEEDS_MORE_FORWARD_CANDIDATES"
    return {
        "mode": "forward-candidate-replay",
        "status": status,
        "candidates_replayed": len(rows_list),
        "replay_decision_counts": counts,
        "top_research_blockers": [{"blocking_reason": key, "count": value} for key, value in sorted(blockers.items(), key=lambda item: item[1], reverse=True)[:10]],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    try:
        return tuple(str(item) for item in value if str(item))
    except TypeError:
        return (str(value),)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
