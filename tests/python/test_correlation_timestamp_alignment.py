"""Correlations pair returns by timestamp and fail closed on short overlap."""

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.portfolio import build_correlation_report, compute_correlation_matrix


def _times(start: int, count: int) -> list[str]:
    base = pd.Timestamp("2026-01-05T00:00:00Z") + pd.Timedelta(minutes=5 * start)
    return list(pd.date_range(base, periods=count, freq="5min").strftime("%Y-%m-%d %H:%M:%S"))


def _walk(count: int, seed: int) -> np.ndarray:
    return 1.1 + np.cumsum(np.random.default_rng(seed).normal(0.0, 0.0001, count))


def _write(path: Path, times: list[str] | None, closes) -> None:
    frame = pd.DataFrame({"close": closes})
    if times is not None:
        frame.insert(0, "time", times)
    frame.to_csv(path, index=False)


def test_series_of_different_lengths_are_paired_on_the_same_bars(tmp_path):
    closes = _walk(80, seed=11)
    _write(tmp_path / "EURUSD_M5.csv", _times(0, 80), closes)
    # Same market moves, but this file starts 20 bars later: row k is not bar k.
    _write(tmp_path / "EURGBP_M5.csv", _times(20, 60), 2.0 * closes[20:])

    report = compute_correlation_matrix(tmp_path, window=80)

    assert report["matrix"]["EURGBP"]["EURUSD"] > 0.999
    assert [(p["symbol_a"], p["symbol_b"]) for p in report["highly_correlated_pairs"]] == [("EURGBP", "EURUSD")]
    assert report["classification"] == "WATCHLIST"
    assert report["insufficient_overlap_pairs"] == []


def test_short_timestamp_overlap_yields_no_correlation(tmp_path):
    closes = _walk(40, seed=5)
    _write(tmp_path / "EURUSD_M5.csv", _times(0, 40), closes)
    # Identical values by row position, but only 5 bars share a timestamp.
    _write(tmp_path / "GBPUSD_M5.csv", _times(35, 40), closes)

    report = compute_correlation_matrix(tmp_path, window=40)

    assert report["matrix"]["EURUSD"]["GBPUSD"] is None
    assert report["matrix"]["GBPUSD"]["EURUSD"] is None
    assert report["highly_correlated_pairs"] == []
    assert report["insufficient_overlap_pairs"] == [{"symbol_a": "EURUSD", "symbol_b": "GBPUSD", "aligned_returns": 4}]
    assert report["classification"] == "WATCHLIST"


def test_file_without_timestamps_cannot_be_aligned(tmp_path):
    closes = _walk(60, seed=3)
    _write(tmp_path / "EURUSD_M5.csv", _times(0, 60), closes)
    _write(tmp_path / "GBPUSD_M5.csv", None, 2.0 * closes)

    report = compute_correlation_matrix(tmp_path, window=60)

    assert report["matrix"]["EURUSD"]["GBPUSD"] is None
    assert report["highly_correlated_pairs"] == []
    assert report["classification"] == "WATCHLIST"


def test_undefined_correlation_is_not_reported_as_uncorrelated(tmp_path):
    _write(tmp_path / "EURUSD_M5.csv", _times(0, 60), _walk(60, seed=9))
    _write(tmp_path / "USDCHF_M5.csv", _times(0, 60), [0.9] * 60)  # Zero variance.

    report = compute_correlation_matrix(tmp_path, window=60)

    assert report["matrix"]["EURUSD"]["USDCHF"] is None
    assert report["classification"] == "WATCHLIST"


def test_independent_aligned_series_are_ok(tmp_path):
    _write(tmp_path / "EURUSD_M5.csv", _times(0, 120), _walk(120, seed=1))
    _write(tmp_path / "USDJPY_M5.csv", _times(0, 120), _walk(120, seed=2))

    report = compute_correlation_matrix(tmp_path, window=120)

    assert abs(report["matrix"]["EURUSD"]["USDJPY"]) < 0.85
    assert report["matrix"]["EURUSD"]["EURUSD"] == pytest.approx(1.0)
    assert report["highly_correlated_pairs"] == report["insufficient_overlap_pairs"] == []
    assert report["classification"] == "OK"


def test_matrix_csv_writes_null_correlations_as_empty_cells(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write(data / "EURUSD_M5.csv", _times(0, 60), _walk(60, seed=9))
    _write(data / "USDCHF_M5.csv", _times(0, 60), [0.9] * 60)  # Zero variance: null diagonal too.

    build_correlation_report(data_dir=data, output_dir=tmp_path / "out", window=60)

    with (tmp_path / "out" / "correlation_matrix.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["symbol", "EURUSD", "USDCHF"]
    assert rows[1][0] == "EURUSD" and float(rows[1][1]) == pytest.approx(1.0) and rows[1][2] == ""
    assert rows[2] == ["USDCHF", "", ""]
