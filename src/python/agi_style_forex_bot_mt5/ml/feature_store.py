"""Feature store builder for ML meta-filter training."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


FEATURE_COLUMNS = (
    "signal_id",
    "timestamp_utc",
    "symbol",
    "symbol_encoded",
    "session_encoded",
    "regime_encoded",
    "strategy_encoded",
    "score",
    "spread_points",
    "spread_percentile",
    "tick_age_seconds",
    "atr_percent",
    "rsi",
    "ema_fast_slow_distance",
    "price_to_ema20",
    "price_to_ema50",
    "volatility_zscore",
    "momentum_3",
    "momentum_5",
    "wick_imbalance",
    "candle_body_ratio",
    "hour_utc",
    "weekday",
    "broker_readiness_score",
    "recent_rejection_rate",
    "recent_paper_winrate",
    "recent_expectancy_r",
    "recent_drawdown_shadow",
    "strategy_candidate_status",
)


def build_feature_store(database: TelemetryDatabase, output_dir: str | Path) -> dict[str, Any]:
    """Build signal-level features from audit events and paper trade context."""

    rows = _rows_from_events(database)
    if not rows:
        rows = _rows_from_paper_trades(database)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "feature_store.csv"
    _write_csv(csv_path, rows, FEATURE_COLUMNS)
    reports = [str(csv_path)]
    parquet_path = output / "feature_store.parquet"
    try:
        import pandas as pd

        frame = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
        frame.to_parquet(parquet_path)
        reports.append(str(parquet_path))
    except Exception:
        pass
    return {
        "mode": "build-ml-feature-store",
        "samples": len(rows),
        "feature_columns": list(FEATURE_COLUMNS),
        "feature_fingerprint": _fingerprint(rows),
        "reports_created": reports,
        "execution_attempted": False,
    }


def _rows_from_events(database: TelemetryDatabase) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in database.fetch_all("events"):
        if event["event_type"] not in {"SIGNAL_DETECTED", "TRADE_SIGNAL_CREATED", "PAPER_TRADE_OPENED"}:
            continue
        try:
            payload = json.loads(event["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        signal_id = str(event["signal_id"] or payload.get("signal_id") or event["correlation_id"])
        if signal_id in seen:
            continue
        seen.add(signal_id)
        rows.append(_feature_row(signal_id, str(event["timestamp_utc"]), str(event["symbol"] or payload.get("symbol") or ""), payload))
    return rows


def _rows_from_paper_trades(database: TelemetryDatabase) -> list[dict[str, Any]]:
    rows = []
    for item in database.fetch_paper_trades():
        payload = json.loads(item["payload_json"])
        rows.append(_feature_row(str(payload.get("signal_id") or payload.get("paper_trade_id")), str(payload.get("entry_time_utc") or item["opened_at_utc"]), str(payload.get("symbol") or ""), payload))
    return rows


def _feature_row(signal_id: str, timestamp: str, symbol: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    strategy = str(payload.get("strategy_name") or payload.get("strategy") or "strategy_ensemble")
    regime = str(payload.get("regime") or payload.get("features", {}).get("regime") or "UNKNOWN")
    session = str(payload.get("session") or payload.get("features", {}).get("session") or "UNKNOWN")
    hour = _safe_hour(timestamp)
    weekday = _safe_weekday(timestamp)
    features = dict(payload.get("features") or payload.get("metadata") or {})
    return {
        "signal_id": signal_id,
        "timestamp_utc": timestamp,
        "symbol": symbol,
        "symbol_encoded": _stable_code(symbol),
        "session_encoded": _stable_code(session),
        "regime_encoded": _stable_code(regime),
        "strategy_encoded": _stable_code(strategy),
        "score": float(payload.get("score") or features.get("score") or 0.0),
        "spread_points": float(payload.get("spread_points") or features.get("spread_points") or payload.get("spread_at_entry") or 0.0),
        "spread_percentile": float(payload.get("spread_percentile") or 50.0),
        "tick_age_seconds": float(payload.get("tick_age_seconds") or 0.0),
        "atr_percent": float(features.get("atr_percent") or payload.get("atr_percent") or 0.0),
        "rsi": float(features.get("rsi") or features.get("rsi14") or payload.get("rsi") or 50.0),
        "ema_fast_slow_distance": float(features.get("ema_fast", 0.0) or 0.0) - float(features.get("ema_slow", 0.0) or 0.0),
        "price_to_ema20": float(features.get("close", 0.0) or 0.0) - float(features.get("ema20", 0.0) or 0.0),
        "price_to_ema50": float(features.get("close", 0.0) or 0.0) - float(features.get("ema50", 0.0) or 0.0),
        "volatility_zscore": float(features.get("volatility_zscore") or features.get("volatility") or 0.0),
        "momentum_3": float(features.get("momentum_3") or features.get("momentum") or 0.0),
        "momentum_5": float(features.get("momentum_5") or features.get("momentum") or 0.0),
        "wick_imbalance": float(features.get("lower_wick", 0.0) or 0.0) - float(features.get("upper_wick", 0.0) or 0.0),
        "candle_body_ratio": float(features.get("body_ratio") or payload.get("candle_body_ratio") or 0.0),
        "hour_utc": hour,
        "weekday": weekday,
        "broker_readiness_score": float(payload.get("broker_readiness_score") or 0.0),
        "recent_rejection_rate": float(payload.get("recent_rejection_rate") or 0.0),
        "recent_paper_winrate": float(payload.get("recent_paper_winrate") or 0.0),
        "recent_expectancy_r": float(payload.get("recent_expectancy_r") or 0.0),
        "recent_drawdown_shadow": float(payload.get("recent_drawdown_shadow") or 0.0),
        "strategy_candidate_status": _stable_code(str(payload.get("strategy_candidate_status") or "UNKNOWN")),
    }


def _stable_code(value: str) -> int:
    return int(hashlib.sha256(value.upper().encode("utf-8")).hexdigest()[:8], 16) % 10000


def _safe_hour(timestamp: str) -> int:
    try:
        return int(timestamp[11:13])
    except Exception:
        return 0


def _safe_weekday(timestamp: str) -> int:
    from datetime import datetime

    try:
        return datetime.fromisoformat(timestamp).weekday()
    except Exception:
        return 0


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

