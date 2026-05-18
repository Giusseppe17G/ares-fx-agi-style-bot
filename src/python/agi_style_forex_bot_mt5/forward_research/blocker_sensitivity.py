"""Research-only blocker sensitivity variants for forward candidates."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


VARIANTS: tuple[str, ...] = (
    "KEEP_CURRENT_BALANCED_STABLE",
    "IGNORE_REGIME_BLOCK_RESEARCH",
    "RELAX_ENSEMBLE_SCORE_5",
    "RELAX_ENSEMBLE_SCORE_10",
    "RELAX_REGIME_AND_SCORE_5",
)


def run_blocker_sensitivity(candidates: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = [dict(candidate) for candidate in candidates]
    variant_rows: list[dict[str, Any]] = []
    for variant in VARIANTS:
        passes = [_variant_passes(row, variant) for row in rows]
        pass_count = sum(1 for item in passes if item)
        variant_rows.append(
            {
                "variant": variant,
                "candidates_evaluated": len(rows),
                "candidates_that_would_pass": pass_count,
                "expected_risk_notes": _risk_note(variant),
                "not_for_demo_live": True,
                "research_only": True,
                "execution_attempted": False,
            }
        )
    summary = {
        "mode": "forward-blocker-sensitivity",
        "status": "OK" if rows else "NEEDS_MORE_FORWARD_CANDIDATES",
        "variants_evaluated": len(variant_rows),
        "best_research_variant": max(variant_rows, key=lambda item: int(item["candidates_that_would_pass"]))["variant"] if variant_rows else "",
        "research_only": True,
        "not_for_demo_live": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    return summary, variant_rows


def _variant_passes(candidate: Mapping[str, Any], variant: str) -> bool:
    blockers = set(_as_tuple(candidate.get("blocking_reasons")))
    thresholds = dict(candidate.get("thresholds_used") or {})
    score = _float(candidate.get("ensemble_score"))
    threshold = _float(thresholds.get("ensemble_min_score", 0.0))
    if variant == "KEEP_CURRENT_BALANCED_STABLE":
        return bool(candidate.get("passed_thresholds")) and not blockers
    if variant == "IGNORE_REGIME_BLOCK_RESEARCH":
        return bool(blockers) and blockers <= {"REGIME_MISMATCH"}
    if variant == "RELAX_ENSEMBLE_SCORE_5":
        return blockers <= {"ENSEMBLE_SCORE_LOW"} and score >= threshold - 5.0
    if variant == "RELAX_ENSEMBLE_SCORE_10":
        return blockers <= {"ENSEMBLE_SCORE_LOW"} and score >= threshold - 10.0
    if variant == "RELAX_REGIME_AND_SCORE_5":
        return blockers <= {"REGIME_MISMATCH", "ENSEMBLE_SCORE_LOW"} and score >= threshold - 5.0
    return False


def _risk_note(variant: str) -> str:
    if "REGIME" in variant:
        return "Research-only: regime guard relaxation can admit context that BALANCED_STABLE intentionally blocks."
    if "SCORE" in variant:
        return "Research-only: score relaxation can admit lower-quality setups and must be backtested."
    return "Current stable filters; no live/shadow changes."


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
