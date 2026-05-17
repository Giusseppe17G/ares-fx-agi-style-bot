from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.calibration import analyze_signal_frequency, get_signal_profile, run_threshold_sweep_report
from agi_style_forex_bot_mt5.data_pipeline import (
    audit_historical_data,
    audit_timestamps,
    build_feature_availability_report,
    normalize_timestamps,
    resolve_historical_data,
)
from agi_style_forex_bot_mt5.mt5_history_exporter import MT5HistoryExporter
from agi_style_forex_bot_mt5.market_structure import run_strategy_diagnose
from agi_style_forex_bot_mt5.real_data_research import load_latest_run_summary


def test_resolver_finds_flat_symbol_timeframe_csv(tmp_path: Path) -> None:
    _write_history(tmp_path / "EURUSD_M5.csv", rows=1200)

    result = resolve_historical_data(tmp_path, symbol="EURUSD", timeframe="M5", min_bars=1000)

    assert result.found is True
    assert result.is_sufficient is True
    assert result.reason is None


def test_timestamp_normalizer_parses_epoch_seconds() -> None:
    frame = pd.DataFrame({"time": [1770000000], "open": [1], "high": [2], "low": [1], "close": [1.5], "tick_volume": [10]})

    result = normalize_timestamps(frame)

    assert result.diagnosis["status"] == "OK"
    assert str(result.frame["timestamp_utc"].dtype).startswith("datetime64")


def test_timestamp_normalizer_parses_epoch_milliseconds() -> None:
    frame = pd.DataFrame({"timestamp": [1770000000000], "open": [1], "high": [2], "low": [1], "close": [1.5], "tick_volume": [10]})

    result = normalize_timestamps(frame)

    assert result.diagnosis["timestamp_source_column"] == "timestamp"
    assert result.frame["timestamp_utc"].dt.year.iloc[0] == 2026


def test_timestamp_normalizer_parses_iso_and_time_column() -> None:
    frame = pd.DataFrame({"time": ["2026-05-16T12:00:00Z", "2026-05-16T12:05:00Z"], "open": [1, 1], "high": [2, 2], "low": [1, 1], "close": [1.5, 1.5], "tick_volume": [10, 11]})

    result = normalize_timestamps(frame)

    assert result.diagnosis["timestamp_source_column"] == "time"
    assert "timestamp_utc" in result.frame.columns


def test_resolver_finds_nested_timeframe_symbol_csv(tmp_path: Path) -> None:
    nested = tmp_path / "M5"
    nested.mkdir()
    _write_history(nested / "EURUSD.csv", rows=1200)

    result = resolve_historical_data(tmp_path, symbol="EURUSD", timeframe="M5", min_bars=1000)

    assert result.found is True
    assert Path(result.path).name == "EURUSD.csv"


def test_resolver_reports_missing_h1_file(tmp_path: Path) -> None:
    _write_history(tmp_path / "EURUSD_M5.csv", rows=1200)

    result = resolve_historical_data(tmp_path, symbol="EURUSD", timeframe="H1", min_bars=200)

    assert result.found is False
    assert result.reason == "MISSING_H1_FILE"


def test_resolver_reports_insufficient_h1_bars(tmp_path: Path) -> None:
    _write_history(tmp_path / "EURUSD_H1.csv", rows=50)

    result = resolve_historical_data(tmp_path, symbol="EURUSD", timeframe="H1", min_bars=200)

    assert result.found is True
    assert result.reason == "INSUFFICIENT_H1_BARS"


def test_h1_859_bars_is_calibration_sufficient_not_full_validation(tmp_path: Path) -> None:
    _write_history(tmp_path / "EURUSD_H1.csv", rows=859)

    calibration = resolve_historical_data(tmp_path, symbol="EURUSD", timeframe="H1", min_bars=200)
    full = resolve_historical_data(tmp_path, symbol="EURUSD", timeframe="H1", min_bars=1000)

    assert calibration.is_sufficient is True
    assert calibration.sufficient_for_calibration is True
    assert calibration.sufficient_for_full_validation is False
    assert full.reason == "INSUFFICIENT_H1_BARS"


def test_calibration_uses_m5_when_h1_partial_for_diagnostics(tmp_path: Path) -> None:
    _write_history(tmp_path / "EURUSD_M5.csv", rows=1200)
    _write_history(tmp_path / "EURUSD_H1.csv", rows=250)

    summary = analyze_signal_frequency(symbols=("EURUSD",), data_dir=tmp_path, profile=get_signal_profile("BALANCED"), max_rows_per_symbol=5)

    assert summary["records"]
    assert summary["top_blocking_reasons"][0]["blocking_reason"] != "DATA_MISSING"
    assert all(record["blocking_reason"] != "DATA_MISSING" for record in summary["records"])


def test_strategy_diagnose_uses_resolver_for_nested_history(tmp_path: Path) -> None:
    nested = tmp_path / "M5"
    nested.mkdir()
    _write_history(nested / "EURUSD.csv", rows=1200)

    summary = run_strategy_diagnose(symbol="EURUSD", data_dir=tmp_path, report_dir=tmp_path / "reports")

    assert summary["required_data_missing"] is False
    assert summary["execution_attempted"] is False


def test_threshold_sweep_uses_specific_missing_reason(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"

    summary = run_threshold_sweep_report(symbols=("EURUSD",), data_dir=tmp_path, report_dir=report_dir, profiles_value="BALANCED")

    assert summary["top_blocking_reasons"][0]["blocking_reason"] == "MISSING_M5_FILE"
    assert "DATA_MISSING" not in {row["blocking_reason"] for row in summary["top_blocking_reasons"]}


def test_historical_data_audit_generates_json_and_csv(tmp_path: Path) -> None:
    report_dir = tmp_path / "audit"
    _write_history(tmp_path / "EURUSD_M5.csv", rows=1200)
    _write_history(tmp_path / "EURUSD_M15.csv", rows=600)
    _write_history(tmp_path / "EURUSD_H1.csv", rows=250)

    summary = audit_historical_data(data_dir=tmp_path, report_dir=report_dir, symbols=("EURUSD",), mode="calibration")

    assert summary["classification"] == "OK"
    assert (report_dir / "historical_data_audit.json").exists()
    assert (report_dir / "historical_data_audit.csv").exists()
    assert summary["execution_attempted"] is False


def test_feature_availability_report_detects_columns(tmp_path: Path) -> None:
    report_dir = tmp_path / "features"
    _write_history(tmp_path / "EURUSD_M5.csv", rows=1200)

    summary = build_feature_availability_report(data_dir=tmp_path, report_dir=report_dir, symbols=("EURUSD",))

    assert summary["features_checked"] > 0
    assert (report_dir / "feature_availability.json").exists()
    assert summary["execution_attempted"] is False


def test_feature_availability_no_timestamp_error_when_time_exists(tmp_path: Path) -> None:
    report_dir = tmp_path / "features"
    _write_history(tmp_path / "EURUSD_M5.csv", rows=1200)

    summary = build_feature_availability_report(data_dir=tmp_path, report_dir=report_dir, symbols=("EURUSD",))

    statuses = {item["status"] for item in summary["unavailable_features"]}
    assert "FEATURE_UNAVAILABLE_DUE_TO_TIMESTAMP" not in statuses


def test_cli_accepts_historical_data_audit(tmp_path: Path, capsys) -> None:
    report_dir = tmp_path / "audit"
    _write_history(tmp_path / "EURUSD_M5.csv", rows=1200)

    assert cli.main(["--mode", "historical-data-audit", "--symbol", "EURUSD", "--data-dir", str(tmp_path), "--report-dir", str(report_dir)]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["mode"] == "historical-data-audit"
    assert output["execution_attempted"] is False


def test_timestamp_audit_generates_json_and_csv(tmp_path: Path, capsys) -> None:
    report_dir = tmp_path / "timestamps"
    _write_history(tmp_path / "EURUSD_M5.csv", rows=1200)

    assert cli.main(["--mode", "timestamp-audit", "--symbol", "EURUSD", "--data-dir", str(tmp_path), "--report-dir", str(report_dir), "--timeframes", "M5"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["mode"] == "timestamp-audit"
    assert (report_dir / "timestamp_audit.json").exists()
    assert (report_dir / "timestamp_audit.csv").exists()
    assert output["execution_attempted"] is False


def test_export_history_writes_timestamp_utc(tmp_path: Path) -> None:
    class FakeMT5:
        TIMEFRAME_M5 = 5

        def initialize(self) -> bool:
            return True

        def symbol_info(self, symbol: str):
            from types import SimpleNamespace

            return SimpleNamespace(name=symbol)

        def copy_rates_from_pos(self, symbol: str, timeframe, start_pos: int, count: int):
            return [{"time": 1770000000, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "tick_volume": 100, "spread": 10}]

        def last_error(self):
            return (0, "")

        def order_send(self, request):
            raise AssertionError("order_send must not be called")

        def order_check(self, request):
            raise AssertionError("order_check must not be called")

    summary = MT5HistoryExporter(symbols=("EURUSD",), timeframes=("M5",), output_dir=tmp_path, mt5_client=FakeMT5()).run()
    frame = pd.read_csv(tmp_path / "EURUSD_M5.csv")

    assert summary.execution_attempted is False
    assert "timestamp_utc" in frame.columns


def test_latest_run_summary_includes_historical_data_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "20260101-010000-real-data-research"
    audit_dir = run_dir / "reports" / "data_audit"
    audit_dir.mkdir(parents=True)
    (run_dir / "final_summary_compact.json").write_text(
        json.dumps({"run_id": run_dir.name, "total_trades": 0, "execution_attempted": False, "order_send_called": False, "order_check_called": False}),
        encoding="utf-8",
    )
    (audit_dir / "historical_data_audit.json").write_text(
        json.dumps(
            {
                "historical_data_status": "NEEDS_MORE_DATA",
                "main_data_blocker": "INSUFFICIENT_H1_BARS",
                "missing_timeframes": [],
                "insufficient_timeframes": [{"symbol": "EURUSD", "timeframe": "H1"}],
            }
        ),
        encoding="utf-8",
    )
    (audit_dir / "feature_availability.json").write_text(json.dumps({"feature_availability_status": "PARTIAL"}), encoding="utf-8")

    summary = load_latest_run_summary(tmp_path)

    assert summary["historical_data_status"] == "NEEDS_MORE_DATA"
    assert summary["feature_availability_status"] == "PARTIAL"
    assert summary["main_data_blocker"] == "INSUFFICIENT_H1_BARS"
    assert summary["recommended_next_action"] == "Export more H1 bars or lower calibration diagnostic minimum only for research."


def _write_history(path: Path, *, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    data = []
    for index in range(rows):
        price = 1.1000 + (index % 50) * 0.00001
        data.append(
            {
                "time": (start + pd.Timedelta(minutes=5 * index)).isoformat(),
                "open": price,
                "high": price + 0.0002,
                "low": price - 0.0002,
                "close": price + 0.00003,
                "tick_volume": 100 + index,
                "spread": 8,
            }
        )
    pd.DataFrame(data).to_csv(path, index=False)
