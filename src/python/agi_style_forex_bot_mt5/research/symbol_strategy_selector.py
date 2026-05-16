"""Symbol-level strategy mix selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .strategy_candidate import StrategyCandidate


def build_symbol_strategy_mix(
    candidates: Iterable[StrategyCandidate],
    *,
    output_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Build recommended strategy mix per symbol from candidate statuses."""

    rows: list[dict[str, Any]] = []
    by_symbol: dict[str, list[StrategyCandidate]] = {}
    for candidate in candidates:
        by_symbol.setdefault(candidate.symbol, []).append(candidate)
    for symbol, items in sorted(by_symbol.items()):
        approved = [item for item in items if item.status == "APPROVED_FOR_SHADOW_OBSERVATION"]
        rejected = [item for item in items if item.status == "REJECTED"]
        accepted_source = approved or [item for item in items if item.status == "WATCHLIST"]
        rows.append(
            {
                "symbol": symbol,
                "approved_strategies": sorted({item.strategy_name for item in approved}),
                "rejected_strategies": sorted({item.strategy_name for item in rejected}),
                "best_regimes": _top_values(accepted_source, "regime"),
                "worst_regimes": _top_values(rejected, "regime"),
                "best_sessions": _top_values(accepted_source, "session"),
                "max_allowed_spread_points": _max_spread(accepted_source),
                "recommended_risk_multiplier": 1.0 if approved else 0.5,
                "notes": "approved candidates available" if approved else "watchlist only; keep shadow/research",
            }
        )
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    return rows


def mix_to_frame(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def _top_values(candidates: Iterable[StrategyCandidate], field: str) -> list[str]:
    values: dict[str, int] = {}
    for candidate in candidates:
        value = str(getattr(candidate, field))
        values[value] = values.get(value, 0) + 1
    return [item[0] for item in sorted(values.items(), key=lambda pair: pair[1], reverse=True)[:3]]


def _max_spread(candidates: Iterable[StrategyCandidate]) -> float:
    values = [
        float(candidate.metrics_summary.get("max_allowed_spread_points", 25.0) or 25.0)
        for candidate in candidates
    ]
    return min(values) if values else 25.0
