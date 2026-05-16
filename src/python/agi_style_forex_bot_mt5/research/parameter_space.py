"""Controlled parameter spaces for strategy research."""

from __future__ import annotations

from itertools import product
from typing import Any, Iterable, Mapping


PARAMETER_SPACES: dict[str, dict[str, tuple[Any, ...]]] = {
    "trend_pullback": {
        "ema_fast": (10, 20, 30),
        "ema_slow": (50, 75, 100),
        "rsi_buy_min": (40, 45, 50),
        "rsi_buy_max": (62, 68, 72),
        "rsi_sell_min": (28, 32, 38),
        "rsi_sell_max": (50, 55, 60),
        "sl_atr_multiplier": (0.8, 1.0, 1.2, 1.5),
        "tp_r_multiplier": (1.0, 1.2, 1.5, 1.8),
        "min_score": (65, 70, 75, 80),
    },
    "mean_reversion": {
        "bollinger_period": (20, 30),
        "bollinger_std": (1.8, 2.0, 2.2),
        "rsi_low": (25, 30, 35),
        "rsi_high": (65, 70, 75),
        "vwap_distance_min": (0.5, 1.0, 1.5),
        "sl_atr_multiplier": (0.8, 1.0, 1.2),
        "tp_r_multiplier": (0.8, 1.0, 1.2),
    },
    "breakout_compression": {
        "bb_width_percentile": (10, 15, 20),
        "atr_percentile_min": (20, 30, 40),
        "breakout_body_ratio": (0.55, 0.65, 0.75),
        "sl_atr_multiplier": (1.0, 1.2, 1.5),
        "tp_r_multiplier": (1.2, 1.5, 2.0),
    },
    "liquidity_sweep": {
        "lookback_bars": (10, 20, 30),
        "wick_ratio_min": (0.5, 0.6, 0.7),
        "reclaim_close_required": (True, False),
        "sl_atr_multiplier": (0.8, 1.0, 1.2),
        "tp_r_multiplier": (1.0, 1.2, 1.5),
    },
    "session_momentum": {
        "session": ("LONDON", "NEW_YORK", "LONDON_NY_OVERLAP"),
        "momentum_lookback": (3, 5, 10),
        "min_atr_percentile": (30, 40, 50),
        "max_spread_percentile": (75, 85, 90),
        "sl_atr_multiplier": (1.0, 1.2, 1.5),
        "tp_r_multiplier": (1.2, 1.5, 1.8),
    },
    "volatility_expansion": {
        "atr_expansion_ratio": (1.2, 1.5, 2.0),
        "volatility_zscore_min": (1.0, 1.5, 2.0),
        "spread_guard_percentile": (75, 85),
        "sl_atr_multiplier": (1.2, 1.5),
        "tp_r_multiplier": (1.5, 2.0),
    },
}


def parameter_grid(strategy_name: str, *, max_candidates: int | None = None) -> tuple[dict[str, Any], ...]:
    """Return deterministic parameter grid for one strategy."""

    space = PARAMETER_SPACES[strategy_name]
    keys = tuple(space)
    rows = [dict(zip(keys, values)) for values in product(*(space[key] for key in keys))]
    if max_candidates is not None:
        rows = rows[: max(0, int(max_candidates))]
    return tuple(rows)


def generate_research_parameter_sets(
    strategies: Iterable[str] | None = None,
    *,
    max_candidates: int = 100,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Return reproducible strategy/params pairs capped across strategies."""

    selected = tuple(strategies or PARAMETER_SPACES.keys())
    grids = {strategy: list(parameter_grid(strategy)) for strategy in selected}
    rows: list[tuple[str, dict[str, Any]]] = []
    index = 0
    while len(rows) < max_candidates:
        added = False
        for strategy in selected:
            if index < len(grids[strategy]):
                rows.append((strategy, grids[strategy][index]))
                added = True
                if len(rows) >= max_candidates:
                    return tuple(rows)
        if not added:
            break
        index += 1
    return tuple(rows)
