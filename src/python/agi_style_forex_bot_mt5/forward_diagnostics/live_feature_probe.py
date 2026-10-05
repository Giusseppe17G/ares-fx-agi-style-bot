"""Build live runtime features and expose missing feature blockers."""

from __future__ import annotations

from typing import Any, Mapping
from dataclasses import replace
from agi_style_forex_bot_mt5.data.strategy_features import build_strategy_features

import pandas as pd

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.data import add_indicators, add_regime_labels
from agi_style_forex_bot_mt5.data_pipeline.live_data_contract import DIAGNOSTIC_MIN_BARS, normalize_ohlcv_contract
from agi_style_forex_bot_mt5.market_structure import build_market_structure_features


CRITICAL_FEATURES: tuple[str, ...] = (
    "ema20",
    "ema50",
    "ema200",
    "rsi14",
    "atr14",
    "atr_percent",
    "ema_slope",
    "trend_strength",
    "momentum",
    "volatility",
)


def probe_live_features(
    *,
    config: BotConfig,
    runtime_payloads: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return feature diagnostics and feature dictionaries by symbol."""

    rows: list[dict[str, Any]] = []
    features_by_symbol: dict[str, dict[str, Any]] = {}
    for symbol, payload in runtime_payloads.items():
        snapshot = payload["snapshot"]
        raw_m5 = dict(payload.get("rates") or {}).get("M5")
        try:
            contract = normalize_ohlcv_contract(raw_m5, source="live_mt5", symbol=symbol, timeframe="M5", min_rows=DIAGNOSTIC_MIN_BARS["M5"])
            if contract.diagnostics["status"] != "OK":
                raise LiveFeatureBuildError(contract.diagnostics["status"], contract.diagnostics)
            frame = contract.frame
            features = _features_from_bars(frame, snapshot, config)
            features_by_symbol[symbol] = features
            rows.append(
                {
                    "symbol": symbol,
                    "features_generated": True,
                    "required_features_available": True,
                    "missing_features": (),
                    "feature_build_errors": "",
                    "regime_detected": features.get("regime", ""),
                    "session_detected": features.get("session", ""),
                    "volatility_state": features.get("volatility", ""),
                    "structure_state": _state(features.get("market_structure")),
                    "liquidity_state": _state(features.get("liquidity")),
                    "spread_points": features.get("spread_points"),
                    "broker_fit": features.get("broker_readiness_score"),
                    "cost_fit": features.get("cost_fit", _cost_fit(features.get("spread_points"), config.max_spread_points_default)),
                    "liquidity_fit": features.get("liquidity_fit"),
                    "momentum_fit": features.get("momentum_fit"),
                    "regime_fit": features.get("regime_fit"),
                    "session_fit": features.get("session_fit"),
                    "structure_fit": features.get("structure_fit"),
                    "volatility_fit": features.get("volatility_fit"),
                    "blockers": (),
                    "feature_build_error_type": "",
                    "feature_build_exception": "",
                    "missing_columns": (),
                    "invalid_dtypes": (),
                    "row_count_by_timeframe": {"M5": len(frame)},
                    "timestamp_status": contract.diagnostics.get("timestamp_status", ""),
                    "null_counts": contract.diagnostics.get("null_counts", {}),
                    "first_timestamp_utc": contract.diagnostics.get("first_timestamp_utc", ""),
                    "last_timestamp_utc": contract.diagnostics.get("last_timestamp_utc", ""),
                    "last_closed_candle_utc": contract.diagnostics.get("last_closed_candle_utc", ""),
                    "schema_before": contract.diagnostics.get("schema_before", ()),
                    "schema_after": contract.diagnostics.get("schema_after", ()),
                    "execution_attempted": False,
                }
            )
        except LiveFeatureBuildError as exc:
            diagnostics = exc.diagnostics
            rows.append(
                {
                    "symbol": symbol,
                    "features_generated": False,
                    "required_features_available": False,
                    "missing_features": (),
                    "feature_build_errors": diagnostics.get("status", exc.code),
                    "feature_build_error_type": diagnostics.get("feature_build_error_type", exc.code),
                    "feature_build_exception": diagnostics.get("error", ""),
                    "missing_columns": diagnostics.get("missing_columns", ()),
                    "invalid_dtypes": diagnostics.get("invalid_dtypes", ()),
                    "row_count_by_timeframe": {"M5": diagnostics.get("rows_after", 0)},
                    "timestamp_status": diagnostics.get("timestamp_status", ""),
                    "null_counts": diagnostics.get("null_counts", {}),
                    "first_timestamp_utc": diagnostics.get("first_timestamp_utc", ""),
                    "last_timestamp_utc": diagnostics.get("last_timestamp_utc", ""),
                    "last_closed_candle_utc": diagnostics.get("last_closed_candle_utc", ""),
                    "schema_before": diagnostics.get("schema_before", ()),
                    "schema_after": diagnostics.get("schema_after", ()),
                    "regime_detected": "",
                    "session_detected": "",
                    "blockers": tuple(diagnostics.get("blockers") or (exc.code,)),
                    "recommended_action": "Increase copy_rates_from_pos bars for live feature probe." if exc.code == "LIVE_INSUFFICIENT_ROWS_FOR_FEATURES" else "",
                    "execution_attempted": False,
                }
            )
        except Exception as exc:
            code = _feature_blocker(str(exc))
            rows.append(
                {
                    "symbol": symbol,
                    "features_generated": False,
                    "required_features_available": False,
                    "missing_features": _missing_from_error(str(exc)),
                    "feature_build_errors": str(exc),
                    "feature_build_error_type": code,
                    "feature_build_exception": str(exc),
                    "missing_columns": (),
                    "invalid_dtypes": (),
                    "row_count_by_timeframe": {},
                    "timestamp_status": "",
                    "null_counts": {},
                    "first_timestamp_utc": "",
                    "last_timestamp_utc": "",
                    "last_closed_candle_utc": "",
                    "schema_before": (),
                    "schema_after": (),
                    "regime_detected": "",
                    "session_detected": "",
                    "blockers": (code,),
                    "execution_attempted": False,
                }
            )
    return rows, features_by_symbol


def _features_from_bars(bars: pd.DataFrame, snapshot: Any, config: BotConfig) -> dict[str, Any]:
    return build_strategy_features(bars, replace(snapshot, timeframe="M5"), max_spread_points=config.max_spread_points_default)


def _cost_fit(spread_points: Any, max_spread_points: float) -> float:
    spread = float(spread_points or 0.0)
    if max_spread_points <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 - (spread / max_spread_points * 100.0)))


def _state(value: Any) -> str:
    return "AVAILABLE" if value else "NOT_DETECTED"


def _feature_blocker(message: str) -> str:
    text = message.upper()
    if text.startswith("LIVE_"):
        return text.split(":", 1)[0]
    if "REGIME" in text:
        return "REGIME_NOT_DETECTED"
    if "STRUCTURE" in text or "INSUFFICIENT" in text:
        return "INSUFFICIENT_STRUCTURE_DATA"
    if "VOLATILITY" in text:
        return "VOLATILITY_NOT_CONFIRMED"
    return "FEATURE_ENGINE_EXCEPTION"


def _missing_from_error(message: str) -> tuple[str, ...]:
    if "missing " not in message:
        return ()
    return tuple(item.strip() for item in message.split("missing ", 1)[1].split(",") if item.strip())


class LiveFeatureBuildError(ValueError):
    def __init__(self, code: str, diagnostics: Mapping[str, Any]) -> None:
        super().__init__(code)
        self.code = code
        self.diagnostics = dict(diagnostics)
