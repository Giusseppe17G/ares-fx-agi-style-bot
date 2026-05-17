"""Feature availability checks for historical datasets."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from ..data import add_indicators, add_regime_labels
from ..market_structure import build_market_structure_features
from .historical_csv_loader import load_historical_csv_contract
from .historical_data_resolver import CALIBRATION_MIN_BARS, resolve_historical_data


FEATURES = (
    "ATR",
    "RSI",
    "EMA20",
    "EMA50",
    "Bollinger",
    "volatility_zscore",
    "momentum_3",
    "momentum_5",
    "swing_points",
    "session_levels",
    "liquidity_sweep",
    "regime_detector",
)


def build_feature_availability_report(
    *,
    data_dir: str | Path,
    report_dir: str | Path,
    symbols: Iterable[str],
) -> dict[str, Any]:
    """Check whether required strategy features can be derived from M5 history."""

    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for symbol in [str(item).strip().upper() for item in symbols if str(item).strip()]:
        resolution = resolve_historical_data(data_dir, symbol=symbol, timeframe="M5", min_bars=CALIBRATION_MIN_BARS["M5"])
        if not resolution.found or resolution.reason in {"MISSING_REQUIRED_COLUMNS", "EMPTY_CSV"} or str(resolution.reason or "").startswith("CSV_PARSE"):
            for feature in FEATURES:
                rows.append({"symbol": symbol, "feature": feature, "available": False, "status": _feature_status(resolution.reason), "reason": resolution.reason or "TIMEFRAME_PATH_NOT_FOUND"})
            continue
        try:
            loaded = load_historical_csv_contract(resolution.path, symbol=symbol, timeframe="M5")
            if loaded.diagnostics["status"] != "OK":
                raise ValueError(str(loaded.diagnostics["status"]))
            normalized = loaded.frame.copy()
            normalized["volume"] = normalized["tick_volume"]
            normalized["spread_points"] = normalized["spread"]
            enriched = add_regime_labels(add_indicators(normalized))
            structure = build_market_structure_features(loaded.frame)
            availability = _availability(enriched, structure)
        except Exception as exc:
            reason = str(exc)
            status = "FEATURE_UNAVAILABLE_DUE_TO_TIMESTAMP" if "timestamp" in reason.lower() or "TIMESTAMP" in reason else "FEATURE_BUILD_ERROR"
            availability = {feature: (False, (status, reason)) for feature in FEATURES}
        for feature, (available, reason) in availability.items():
            if isinstance(reason, tuple):
                status, detail = reason
            else:
                status, detail = ("FEATURE_AVAILABLE" if available else "FEATURE_BUILD_ERROR", reason)
            rows.append({"symbol": symbol, "feature": feature, "available": bool(available), "status": status, "reason": detail})
    status = "OK" if rows and all(row["available"] for row in rows) else "PARTIAL"
    summary = {
        "mode": "feature-availability",
        "classification": status,
        "feature_availability_status": status,
        "features_checked": len(rows),
        "unavailable_features": [row for row in rows if not row["available"]],
        "main_feature_blocker": next((row["status"] for row in rows if not row["available"]), ""),
        "reports_created": [str(output / "feature_availability.json"), str(output / "feature_availability.csv"), str(output / "by_symbol.csv"), str(output / "by_feature.csv")],
        "execution_attempted": False,
    }
    (output / "feature_availability.json").write_text(json.dumps(_jsonable({**summary, "features": rows}), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(output / "feature_availability.csv", rows)
    pd.DataFrame(rows).groupby(["symbol", "status"]).size().reset_index(name="count").to_csv(output / "by_symbol.csv", index=False)
    pd.DataFrame(rows).groupby(["feature", "status"]).size().reset_index(name="count").to_csv(output / "by_feature.csv", index=False)
    return summary


def _availability(enriched: pd.DataFrame, structure: Mapping[str, Any]) -> dict[str, tuple[bool, tuple[str, str]]]:
    checks = {
        "ATR": ("atr14", "atr"),
        "RSI": ("rsi14", "rsi"),
        "EMA20": ("ema20",),
        "EMA50": ("ema50",),
        "Bollinger": ("bb_upper", "bb_lower"),
        "volatility_zscore": ("volatility_zscore", "volatility"),
        "momentum_3": ("momentum_3", "momentum"),
        "momentum_5": ("momentum_5", "momentum"),
    }
    result: dict[str, tuple[bool, tuple[str, str]]] = {}
    for feature, columns in checks.items():
        available = any(column in enriched.columns and enriched[column].notna().any() for column in columns)
        result[feature] = (available, ("FEATURE_AVAILABLE", "") if available else ("FEATURE_UNAVAILABLE_DUE_TO_INSUFFICIENT_BARS", "FEATURE_COLUMN_UNAVAILABLE"))
    result["swing_points"] = (bool(structure.get("market_structure")), ("FEATURE_AVAILABLE", "") if structure.get("market_structure") else ("FEATURE_BUILD_ERROR", "STRUCTURE_UNAVAILABLE"))
    result["session_levels"] = (bool(structure.get("session_levels")), ("FEATURE_AVAILABLE", "") if structure.get("session_levels") else ("FEATURE_BUILD_ERROR", "SESSION_LEVELS_UNAVAILABLE"))
    result["liquidity_sweep"] = (bool(structure.get("liquidity")), ("FEATURE_AVAILABLE", "") if structure.get("liquidity") else ("FEATURE_BUILD_ERROR", "LIQUIDITY_UNAVAILABLE"))
    result["regime_detector"] = ("regime" in enriched.columns, ("FEATURE_AVAILABLE", "") if "regime" in enriched.columns else ("FEATURE_BUILD_ERROR", "REGIME_UNAVAILABLE"))
    return result


def _feature_status(reason: str | None) -> str:
    text = str(reason or "")
    if "TIMESTAMP" in text:
        return "FEATURE_UNAVAILABLE_DUE_TO_TIMESTAMP"
    if "MISSING_REQUIRED_COLUMNS" in text:
        return "FEATURE_UNAVAILABLE_DUE_TO_MISSING_COLUMNS"
    if "INSUFFICIENT" in text:
        return "FEATURE_UNAVAILABLE_DUE_TO_INSUFFICIENT_BARS"
    return "FEATURE_BUILD_ERROR"


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["symbol", "feature", "available", "reason"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
