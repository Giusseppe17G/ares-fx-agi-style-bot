"""Absent bar spread is missing cost evidence, never zero cost (PROJECT_SPEC 12.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting import load_historical_csv
from agi_style_forex_bot_mt5.calibration import analyze_signal_frequency, get_signal_profile
from agi_style_forex_bot_mt5.data_pipeline import (
    build_broker_cost_profile,
    build_dataset_manifest,
    build_strategy_data_contract_report,
    cost_for_symbol,
    load_historical_csv_contract,
    scan_history_directory,
)
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


@pytest.mark.parametrize("source", ["historical", "live_mt5", "HISTORICAL", "historical_csv", "csv"])
def test_rates_without_spread_fail_closed_for_every_source(source: str) -> None:
    result = normalize_ohlcv_contract(_bars(), source=source, symbol="EURUSD", timeframe="M5", min_rows=0)

    assert result.diagnostics["status"] == "SPREAD_DATA_MISSING"
    assert "SPREAD_DATA_MISSING" in result.diagnostics["blockers"]
    assert "spread" in result.diagnostics["missing_columns"]


def test_contract_accepts_no_substitute_spread_argument() -> None:
    # No caller-supplied snapshot may stand in for missing bar spread.
    with pytest.raises(TypeError):
        normalize_ohlcv_contract(_bars(), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=0, measured_spread_points=12.0)  # type: ignore[call-arg]


def test_live_rates_with_spread_keep_their_own_values() -> None:
    result = normalize_ohlcv_contract(_bars(spread=7), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=0)

    assert result.diagnostics["status"] == "OK"
    assert (result.frame["spread_points"] == 7.0).all()


def test_live_rates_with_explicit_zero_spread_are_an_observation() -> None:
    result = normalize_ohlcv_contract(_bars(spread=0), source="live_mt5", symbol="EURUSD", timeframe="M5", min_rows=0)

    assert result.diagnostics["status"] == "OK"
    assert (result.frame["spread_points"] == 0.0).all()


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


def _mixed_history(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(data_dir / "EURUSD_M5.csv", rows=120, spread=8)
    _write_csv(data_dir / "GBPUSD_M5.csv", rows=120)
    return data_dir


def test_cost_profile_blocks_symbol_without_spread_and_profiles_the_others(tmp_path: Path) -> None:
    data_dir = _mixed_history(tmp_path / "historical")
    report_dir = tmp_path / "broker_costs"

    profile = build_broker_cost_profile(data_dir=data_dir, report_dir=report_dir)

    assert sorted(profile["symbols"]) == ["EURUSD"]
    assert profile["symbols"]["EURUSD"]["spread_p95"] == 8.0
    assert profile["blocked_symbols"]["GBPUSD"]["reason"] == "SPREAD_DATA_MISSING"
    assert profile["blocked_symbols"]["GBPUSD"]["file_path"].endswith("GBPUSD_M5.csv")
    assert profile["classification"] == "WATCHLIST"
    assert profile["execution_attempted"] is False
    written = json.loads((report_dir / "broker_cost_profile.json").read_text(encoding="utf-8"))
    assert written["blocked_symbols"] == profile["blocked_symbols"]
    # A blocked symbol has no zero p95; consumers fall back to their own default.
    assert cost_for_symbol(written, "GBPUSD", fallback=15.0) == 15.0


def test_cost_profile_with_only_missing_spread_is_not_ok(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    _write_csv(data_dir / "GBPUSD_M5.csv", rows=120)

    profile = build_broker_cost_profile(data_dir=data_dir, report_dir=tmp_path / "broker_costs", symbols=("GBPUSD",))

    assert profile["symbols"] == {}
    assert profile["blocked_symbols"]["GBPUSD"]["reason"] == "SPREAD_DATA_MISSING"
    assert profile["classification"] == "WATCHLIST"


def test_cost_profile_still_raises_other_loader_errors(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    _bars(120, spread=8).drop(columns=["close"]).to_csv(data_dir / "EURUSD_M5.csv", index=False)

    with pytest.raises(ValueError, match="CSV_MISSING_OHLC"):
        build_broker_cost_profile(data_dir=data_dir, report_dir=tmp_path / "broker_costs")


@pytest.mark.parametrize("select_symbols", [True, False])
def test_data_quality_rejects_file_without_spread_and_scans_the_others(tmp_path: Path, select_symbols: bool) -> None:
    data_dir = _mixed_history(tmp_path / "historical")
    report_dir = tmp_path / "data_quality"
    symbols = ("EURUSD", "GBPUSD") if select_symbols else None

    summary = build_dataset_manifest(data_dir=data_dir, report_dir=report_dir, symbols=symbols, timeframes=("M5",))

    assert summary["files_scanned"] == 2
    assert summary["classification"] == "REJECTED"
    assert summary["rejected_files"] == [{"symbol": "GBPUSD", "timeframe": "M5", "reason": "SPREAD_DATA_MISSING"}]
    assert summary["execution_attempted"] is False
    manifest = json.loads((report_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    by_symbol = {item["symbol"]: item for item in manifest["files"]}
    assert by_symbol["EURUSD"]["rejection_reason"] == ""
    assert by_symbol["EURUSD"]["rows"] == 120
    assert by_symbol["EURUSD"]["spread_p95"] == 8.0
    assert by_symbol["GBPUSD"]["classification"] == "REJECTED"
    assert by_symbol["GBPUSD"]["rejection_reason"] == "SPREAD_DATA_MISSING"
    assert by_symbol["GBPUSD"]["spread_p95"] is None
    table = pd.read_csv(report_dir / "by_symbol_timeframe.csv", keep_default_na=False)
    assert dict(zip(table["symbol"], table["rejection_reason"])) == {"EURUSD": "", "GBPUSD": "SPREAD_DATA_MISSING"}


def test_data_quality_with_only_missing_spread_writes_a_rejected_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    _write_csv(data_dir / "GBPUSD_M5.csv", rows=120)

    summary = scan_history_directory(data_dir, report_dir=tmp_path / "data_quality", timeframes=("M5",))

    assert summary["classification"] == "REJECTED"
    assert summary["rejected_files"] == [{"symbol": "GBPUSD", "timeframe": "M5", "reason": "SPREAD_DATA_MISSING"}]
    assert (tmp_path / "data_quality" / "summary.json").exists()
