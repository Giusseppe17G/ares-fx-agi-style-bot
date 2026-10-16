"""Absent bar spread is missing cost evidence, never zero cost (PROJECT_SPEC 12.3)."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting import load_historical_csv
from agi_style_forex_bot_mt5.calibration import analyze_signal_frequency, get_signal_profile
from agi_style_forex_bot_mt5.data_pipeline import build_strategy_data_contract_report, load_historical_csv_contract
from agi_style_forex_bot_mt5.data_pipeline.live_data_contract import normalize_ohlcv_contract


def _bars(rows: int = 60, *, spread: float | None = None) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-05", periods=rows, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "time": [int(value.timestamp()) for value in timestamps],
            "open": [1.1000 + index * 0.00001 for index in range(rows)],
            "high": [1.1003 + index * 0.00001 for index in range(rows)],
            "low": [1.0997 + index * 0.00001 for index in range(rows)],
            "close": [1.1001 + index * 0.00001 for index in range(rows)],
            "tick_volume": 100,
        }
    )
    if spread is not None:
        frame["spread"] = spread
    return frame


def _write_csv(path: Path, *, rows: int = 60, spread: float | None = None) -> Path:
    frame = _bars(rows, spread=spread)
    frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    frame.to_csv(path, index=False)
    return path


def test_historical_csv_without_spread_fails_closed(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "EURUSD_M5.csv")

    result = load_historical_csv_contract(path, symbol="EURUSD", timeframe="M5")

    assert result.diagnostics["status"] == "SPREAD_DATA_MISSING"
    assert "spread" in result.diagnostics["missing_columns"]
    assert "CSV_SPREAD_MISSING_ASSUMED_ZERO" not in result.diagnostics["warnings"]


def test_backtester_load_refuses_csv_without_spread(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "EURUSD_M5.csv")

    with pytest.raises(ValueError, match="SPREAD_DATA_MISSING"):
        load_historical_csv(path, symbol="EURUSD", timeframe="M5")


def test_explicit_zero_spread_is_an_observation_and_is_preserved(tmp_path: Path) -> None:
    path = _write_csv(tmp_path / "EURUSD_M5.csv", spread=0)

    contract = load_historical_csv_contract(path, symbol="EURUSD", timeframe="M5")
    frame, _quality = load_historical_csv(path, symbol="EURUSD", timeframe="M5")

    assert contract.diagnostics["status"] == "OK"
    assert (contract.frame["spread"] == 0).all()
    assert (frame["spread_points"] == 0).all()


def test_historical_contract_never_imputes_spread_even_with_a_measured_value() -> None:
    # A current measurement is not the historical cost of past bars.
    result = normalize_ohlcv_contract(_bars(), source="historical", symbol="EURUSD", timeframe="M5", min_rows=0, measured_spread_points=10.0)

    assert result.diagnostics["status"] == "SPREAD_DATA_MISSING"
    assert "SPREAD_DATA_MISSING" in result.diagnostics["blockers"]


def test_live_rates_without_spread_fail_closed() -> None:
    result = normalize_ohlcv_contract(_bars(), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=0)

    assert result.diagnostics["status"] == "SPREAD_DATA_MISSING"
    assert "spread" in result.diagnostics["missing_columns"]


def test_live_rates_without_spread_use_the_caller_measured_spread() -> None:
    result = normalize_ohlcv_contract(_bars(), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=0, measured_spread_points=12.0)

    assert result.diagnostics["status"] == "OK"
    assert (result.frame["spread"] == 12.0).all()
    assert (result.frame["spread_points"] == 12.0).all()
    assert "LIVE_SPREAD_FROM_MEASURED_SNAPSHOT" in result.diagnostics["blockers"]


def test_live_rates_with_spread_keep_their_own_values() -> None:
    result = normalize_ohlcv_contract(_bars(spread=7), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=0, measured_spread_points=12.0)

    assert result.diagnostics["status"] == "OK"
    assert (result.frame["spread_points"] == 7.0).all()
    assert "LIVE_SPREAD_FROM_MEASURED_SNAPSHOT" not in result.diagnostics["blockers"]


@pytest.mark.parametrize("measured", [-1.0, math.nan, math.inf, "bad"])
def test_invalid_measured_live_spread_is_rejected(measured: object) -> None:
    result = normalize_ohlcv_contract(_bars(), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=0, measured_spread_points=measured)  # type: ignore[arg-type]

    assert result.diagnostics["status"] == "SPREAD_DATA_INVALID"


def test_strategy_data_contract_report_blocks_csv_without_spread(tmp_path: Path) -> None:
    _write_csv(tmp_path / "EURUSD_M5.csv")

    summary = build_strategy_data_contract_report(data_dir=tmp_path, report_dir=tmp_path / "report", symbols=("EURUSD",), timeframes=("M5",))

    assert summary["strategy_input_ready_symbols"] == []
    assert {"blocker": "SPREAD_DATA_MISSING", "count": 1} in summary["csv_blockers"]


def test_signal_frequency_reports_missing_spread_not_missing_ohlc(tmp_path: Path) -> None:
    _write_csv(tmp_path / "EURUSD_M5.csv", rows=1_050)

    summary = analyze_signal_frequency(symbols=("EURUSD",), data_dir=tmp_path, profile=get_signal_profile("BALANCED"), max_rows_per_symbol=5)

    record = summary["records"][0]
    assert record["raw_blocking_reason"] == "SPREAD_DATA_MISSING"
    assert record["blocking_reason"] == "SPREAD_DATA_MISSING"
    assert record["accepted_candidate"] is False
