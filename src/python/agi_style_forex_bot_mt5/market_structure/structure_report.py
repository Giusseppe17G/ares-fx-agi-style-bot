"""Market structure report generation and strategy diagnostics."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from agi_style_forex_bot_mt5.contracts import MarketSnapshot, utc_now
from agi_style_forex_bot_mt5.strategy import evaluate_ensemble

from .liquidity_zones import detect_liquidity_zones
from .market_structure import analyze_market_structure
from .price_action_features import calculate_price_action_features
from .session_levels import calculate_session_levels
from .volatility_context import calculate_volatility_context


def build_market_structure_features(frame: pd.DataFrame, *, point: float = 0.00001) -> dict[str, Any]:
    """Build feature overlay from OHLCV history for strategies and reports."""

    structure = analyze_market_structure(frame)
    liquidity = detect_liquidity_zones(frame, point=point)
    sessions = calculate_session_levels(frame)
    volatility = calculate_volatility_context(frame)
    price_action = calculate_price_action_features(frame)
    latest = frame.iloc[-1] if not frame.empty else {}
    payload: dict[str, Any] = {
        "market_structure": structure.to_dict(),
        "liquidity": liquidity.to_dict(),
        "session_levels": sessions.to_dict(),
        "volatility_context": volatility.to_dict(),
        "price_action": price_action.to_dict(),
        "trend_structure": structure.trend_structure,
        "break_of_structure": structure.break_of_structure,
        "change_of_character": structure.change_of_character,
        "swept_prev_high": liquidity.swept_recent_high,
        "swept_prev_low": liquidity.swept_recent_low,
        "reclaimed_high": liquidity.reclaimed_high,
        "reclaimed_low": liquidity.reclaimed_low,
        "session": sessions.current_session,
        "atr_percentile": volatility.atr_percentile,
        "range_compression": volatility.range_compression,
        "expansion_candle": volatility.expansion_candle,
        "upper_wick_ratio": price_action.upper_wick_ratio,
        "lower_wick_ratio": price_action.lower_wick_ratio,
        "body_ratio": price_action.candle_body_quality,
        "wick_rejection": price_action.wick_rejection,
    }
    if isinstance(latest, pd.Series):
        for key in ("open", "high", "low", "close", "tick_volume", "spread"):
            if key in latest:
                payload[key] = float(latest[key])
    return payload


def write_structure_report(*, symbols: Iterable[str], data_dir: str | Path, report_dir: str | Path) -> dict[str, Any]:
    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for symbol in [item.strip().upper() for item in symbols if item.strip()]:
        frame = _load_symbol_frame(Path(data_dir), symbol)
        features = build_market_structure_features(frame)
        rows.append(
            {
                "symbol": symbol,
                "trend_structure": features.get("trend_structure"),
                "break_of_structure": features.get("break_of_structure"),
                "change_of_character": features.get("change_of_character"),
                "session": features.get("session"),
                "atr_percentile": features.get("atr_percentile"),
                "liquidity_sweep": features.get("liquidity", {}).get("sweep_direction"),
            }
        )
    csv_path = output / "structure_summary.csv"
    json_path = output / "structure_summary.json"
    html_path = output / "report.html"
    _write_rows(csv_path, rows)
    summary = {"mode": "structure-report", "symbols": rows, "reports_created": [str(json_path), str(csv_path), str(html_path)], "execution_attempted": False}
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    html_path.write_text("<html><body><h1>Market Structure</h1><pre>" + json.dumps(summary, indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return summary


def run_strategy_diagnose(*, symbol: str, data_dir: str | Path, report_dir: str | Path) -> dict[str, Any]:
    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = _load_symbol_frame(Path(data_dir), symbol.upper())
    features = build_market_structure_features(frame)
    features.setdefault("regime", "TREND_UP" if features.get("trend_structure") == "UP" else "TREND_DOWN" if features.get("trend_structure") == "DOWN" else "RANGE")
    features.setdefault("ema_fast", features.get("close", 1.0))
    features.setdefault("ema_slow", features.get("close", 1.0))
    features.setdefault("atr_points", 10)
    snapshot = _snapshot_from_frame(symbol.upper(), frame)
    signal = evaluate_ensemble(snapshot, features, mode="shadow")
    payload = {
        "mode": "strategy-diagnose",
        "symbol": symbol.upper(),
        "signal": signal.action.value,
        "score": signal.score,
        "reasons": signal.reasons,
        "metadata": dict(signal.metadata),
        "execution_attempted": False,
    }
    json_path = output / f"{symbol.upper()}_strategy_diagnose.json"
    json_path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    return {**payload, "reports_created": [str(json_path)]}


def _load_symbol_frame(data_dir: Path, symbol: str) -> pd.DataFrame:
    for candidate in (data_dir / f"{symbol}_M5.csv", data_dir / f"{symbol}.csv"):
        if candidate.exists():
            frame = pd.read_csv(candidate)
            if "time" in frame.columns:
                frame = frame.sort_values("time")
            return frame
    raise FileNotFoundError(f"no M5 CSV for {symbol}")


def _snapshot_from_frame(symbol: str, frame: pd.DataFrame) -> MarketSnapshot:
    last = frame.iloc[-1]
    close = float(last.get("close", 1.0))
    spread = float(last.get("spread", 10.0))
    point = 0.00001
    return MarketSnapshot(symbol, "M5", utc_now(), close, close + spread * point, spread, 5, point, 1.0, point, 0.01, 100.0, 0.01, 10, 5)


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["symbol"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value

