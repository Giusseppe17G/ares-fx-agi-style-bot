"""Walk-forward failure analyzer for BALANCED robustness warnings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..robustness_validation.robustness_runner import load_balanced_trades, normalize_trade_frame
from .fold_diagnostics import build_fold_diagnostics
from .regime_session_stability import analyze_regime_session_stability
from .strategy_stability_selector import select_stable_strategies
from .symbol_stability_selector import select_stable_symbols
from .temporal_edge_decay import analyze_temporal_edge_decay


def analyze_walk_forward_failures(
    *,
    runs_root: str | Path,
    robustness_dir: str | Path,
    profile_runs_dir: str | Path,
) -> dict[str, Any]:
    """Load robustness artifacts and identify unstable folds/groups."""

    robustness = _read_json(Path(robustness_dir) / "walk_forward_fast.json")
    robustness_folds = _read_csv(Path(robustness_dir) / "walk_forward_fast.csv")
    trades, source, metrics_source = load_balanced_trades(runs_root=runs_root, profile_runs_dir=profile_runs_dir, profile="BALANCED")
    trades = normalize_trade_frame(trades)
    fold_count = int(robustness.get("fold_count", len(robustness_folds) or 3) or 3)
    folds = build_fold_diagnostics(trades, folds=max(1, fold_count))
    edge_decay = analyze_temporal_edge_decay(folds, trades)
    symbols = select_stable_symbols(trades, fold_count=max(1, fold_count))
    strategies = select_stable_strategies(trades, fold_count=max(1, fold_count))
    session_regime = analyze_regime_session_stability(trades)
    negative = folds.loc[(pd.to_numeric(folds["expectancy_r"], errors="coerce") < 0) | (pd.to_numeric(folds["profit_factor"], errors="coerce") < 1.0)] if not folds.empty else pd.DataFrame()
    decision = "STABILITY_REPAIR_REQUIRED" if not negative.empty or edge_decay["classification"] == "TEMPORAL_EDGE_DECAY" else "STABILITY_OK"
    return {
        "decision": decision,
        "walk_forward_classification": robustness.get("classification", ""),
        "trades_source": source,
        "metrics_source": metrics_source,
        "folds_negative": int(len(negative)),
        "fold_diagnostics": folds,
        "edge_decay": edge_decay,
        "symbols": symbols,
        "strategies": strategies,
        "session_regime": session_regime,
        "execution_attempted": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError):
        return pd.DataFrame()
