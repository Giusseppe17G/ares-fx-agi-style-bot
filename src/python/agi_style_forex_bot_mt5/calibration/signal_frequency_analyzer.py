"""Signal frequency analysis over historical CSVs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from ..backtesting.backtester import _features_from_row, _snapshot_from_row, load_historical_csv
from ..config import BotConfig
from ..contracts import SignalAction
from ..data import add_indicators, add_regime_labels
from ..strategy import evaluate_ensemble
from .signal_profile import SignalProfileSettings


def analyze_signal_frequency(
    *,
    symbols: Iterable[str],
    data_dir: str | Path,
    profile: SignalProfileSettings,
    max_rows_per_symbol: int = 600,
) -> dict[str, Any]:
    """Analyze accepted and near-miss signals without creating trades."""

    records: list[dict[str, Any]] = []
    for symbol in [str(item).strip().upper() for item in symbols if str(item).strip()]:
        csv_path = _find_csv(Path(data_dir), symbol)
        if csv_path is None:
            records.append(_record(symbol=symbol, action="NONE", blocking_reason="missing M5 CSV", required_data_missing=True))
            continue
        try:
            candles, _quality = load_historical_csv(csv_path, symbol=symbol, timeframe="M5")
            enriched = _enrich(candles)
        except Exception as exc:
            records.append(_record(symbol=symbol, action="NONE", blocking_reason=f"invalid history: {exc}", required_data_missing=True))
            continue
        cfg = BotConfig()
        start = 220 if len(enriched) > 240 else max(0, len(enriched) // 2)
        indexes = list(range(start, max(start, len(enriched) - 1), max(1, int(max(1, len(enriched) - start) / max_rows_per_symbol))))
        for idx in indexes[:max_rows_per_symbol]:
            row = enriched.iloc[idx]
            try:
                snapshot = _snapshot_from_row(row, symbol=symbol, timeframe="M5", point=0.01 if "JPY" in symbol else 0.00001, config=cfg)
                features = _features_from_row(enriched, idx, snapshot, cfg)
                signal = evaluate_ensemble(snapshot, features, mode="shadow")
                metadata = dict(signal.metadata)
                setup_score = float(metadata.get("setup_quality_score", signal.score if signal.action != SignalAction.NONE else 0.0) or 0.0)
                component_scores = dict(metadata.get("component_scores") or {})
                near = is_near_miss(setup_score=setup_score, threshold=profile.min_setup_score, blocking_reasons=metadata.get("blocking_reasons", ()), window=profile.near_miss_window)
                accepted = signal.action != SignalAction.NONE and signal.score >= profile.ensemble_min_score and _components_pass(component_scores, profile)
                records.append(
                    {
                        "symbol": symbol,
                        "strategy": signal.strategy_name,
                        "action": signal.action.value,
                        "score": signal.score,
                        "setup_score": setup_score,
                        "threshold": profile.min_setup_score,
                        "near_miss": near,
                        "accepted_candidate": accepted,
                        "blocking_reason": _first(metadata.get("blocking_reasons") or signal.reasons),
                        "missing_components": _missing_components(component_scores, profile),
                        "suggested_relaxation": _suggested_relaxation(component_scores, profile, setup_score),
                        "regime": str(features.get("regime", "")),
                        "session": str(features.get("session", "")),
                        "component_scores": component_scores,
                        "execution_attempted": False,
                    }
                )
            except Exception as exc:
                records.append(_record(symbol=symbol, action="NONE", blocking_reason=f"analysis error: {exc}", required_data_missing=True))
    frame = pd.DataFrame(records)
    signals_found = int((frame.get("action", pd.Series(dtype=str)) != "NONE").sum()) if not frame.empty else 0
    near_misses = int(frame.get("near_miss", pd.Series(dtype=bool)).fillna(False).sum()) if not frame.empty else 0
    accepted = int(frame.get("accepted_candidate", pd.Series(dtype=bool)).fillna(False).sum()) if not frame.empty else 0
    return {
        "records": records,
        "signals_found": signals_found,
        "near_misses": near_misses,
        "accepted_candidates": accepted,
        "blocked_candidates": max(0, len(records) - accepted),
        "approximate_trade_candidates": accepted,
        "average_setup_score": float(frame["setup_score"].mean()) if not frame.empty and "setup_score" in frame else 0.0,
        "execution_attempted": False,
    }


def is_near_miss(*, setup_score: float, threshold: float, blocking_reasons: Any, window: float = 8.0) -> bool:
    """Return True when a blocked setup is near a profile threshold."""

    has_block = bool(blocking_reasons)
    return has_block and threshold - window <= setup_score < threshold


def _enrich(candles: pd.DataFrame) -> pd.DataFrame:
    frame = candles.rename(columns={"timestamp": "timestamp_utc"}).copy()
    frame["volume"] = frame.get("volume", frame.get("tick_volume", 0))
    if "spread_points" not in frame.columns:
        frame["spread_points"] = frame.get("spread", 10)
    enriched = add_regime_labels(add_indicators(frame), max_spread_points=25.0)
    return enriched


def _components_pass(component_scores: Mapping[str, Any], profile: SignalProfileSettings) -> bool:
    if not component_scores:
        return False
    checks = {
        "cost_fit": profile.cost_fit_min,
        "structure_fit": profile.structure_fit_min,
        "volatility_fit": profile.volatility_fit_min,
        "session_fit": profile.session_fit_min,
    }
    for name, threshold in checks.items():
        if float(component_scores.get(name, 0.0) or 0.0) < threshold:
            return False
    return min(float(value) for value in component_scores.values()) >= profile.min_component_score


def _missing_components(component_scores: Mapping[str, Any], profile: SignalProfileSettings) -> tuple[str, ...]:
    thresholds = {
        "cost_fit": profile.cost_fit_min,
        "structure_fit": profile.structure_fit_min,
        "volatility_fit": profile.volatility_fit_min,
        "session_fit": profile.session_fit_min,
    }
    return tuple(name for name, threshold in thresholds.items() if float(component_scores.get(name, 0.0) or 0.0) < threshold)


def _suggested_relaxation(component_scores: Mapping[str, Any], profile: SignalProfileSettings, setup_score: float) -> str:
    missing = _missing_components(component_scores, profile)
    if missing:
        return "review " + ", ".join(missing)
    if setup_score < profile.min_setup_score:
        return f"consider min_setup_score {max(50, int(setup_score // 5 * 5))}"
    return "none"


def _find_csv(data_dir: Path, symbol: str) -> Path | None:
    for candidate in (data_dir / f"{symbol}_M5.csv", data_dir / f"{symbol}.csv"):
        if candidate.exists():
            return candidate
    return None


def _first(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return str(next(iter(value), ""))
    except TypeError:
        return str(value)


def _record(*, symbol: str, action: str, blocking_reason: str, required_data_missing: bool = False) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "strategy": "",
        "action": action,
        "score": 0.0,
        "setup_score": 0.0,
        "threshold": 0.0,
        "near_miss": False,
        "accepted_candidate": False,
        "blocking_reason": blocking_reason,
        "missing_components": (),
        "suggested_relaxation": "",
        "regime": "",
        "session": "",
        "component_scores": {},
        "required_data_missing": required_data_missing,
        "execution_attempted": False,
    }
