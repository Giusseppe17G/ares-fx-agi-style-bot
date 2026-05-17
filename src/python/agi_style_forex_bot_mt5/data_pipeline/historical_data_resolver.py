"""Historical CSV discovery and audit helpers."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .timestamp_normalizer import normalize_timestamps

TIMESTAMP_INPUT_COLUMNS = ("timestamp_utc", "timestamp", "datetime", "date", "time")
REQUIRED_HISTORY_COLUMNS = ("open", "high", "low", "close", "tick_volume")
FULL_VALIDATION_MIN_BARS = {"M5": 50_000, "M15": 30_000, "H1": 10_000}
CALIBRATION_MIN_BARS = {"M5": 1_000, "M15": 500, "H1": 200}


@dataclass(frozen=True)
class HistoricalDataResolution:
    """Result for one symbol/timeframe lookup."""

    symbol: str
    timeframe: str
    path: str
    found: bool
    rows: int
    columns: tuple[str, ...]
    missing_columns: tuple[str, ...]
    is_sufficient: bool
    reason: str | None
    start_utc: str = ""
    end_utc: str = ""
    duplicate_timestamps: int = 0
    timestamps_ordered: bool = True
    has_spread: bool = False
    timestamp_source_column: str = ""
    timestamp_status: str = ""
    timestamp_min: str = ""
    timestamp_max: str = ""
    timeframe_detected: str = ""
    required_rows_full_validation: int = 0
    required_rows_calibration: int = 0
    sufficient_for_full_validation: bool = False
    sufficient_for_calibration: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_historical_data(
    data_dir: str | Path,
    *,
    symbol: str,
    timeframe: str,
    min_bars: int | None = None,
    broker_symbol: str | None = None,
) -> HistoricalDataResolution:
    """Find and validate one historical CSV across supported path patterns."""

    root = Path(data_dir)
    canonical = symbol.strip().upper()
    tf = timeframe.strip().upper()
    required_bars = int(min_bars if min_bars is not None else CALIBRATION_MIN_BARS.get(tf, 0))
    full_required = FULL_VALIDATION_MIN_BARS.get(tf, 0)
    calibration_required = CALIBRATION_MIN_BARS.get(tf, 0)
    candidates = _candidate_paths(root, canonical, tf, broker_symbol=broker_symbol)
    existing = next((path for path in candidates if path.exists() and path.is_file()), None)
    if existing is None:
        return _resolution(canonical, tf, "", False, 0, (), REQUIRED_HISTORY_COLUMNS, False, f"MISSING_{tf}_FILE", full_required=full_required, calibration_required=calibration_required)
    try:
        frame = pd.read_csv(existing)
    except Exception as exc:
        return _resolution(canonical, tf, str(existing), True, 0, (), REQUIRED_HISTORY_COLUMNS, False, f"CSV_PARSE_ERROR: {exc}", full_required=full_required, calibration_required=calibration_required)
    if frame.empty:
        return _resolution(canonical, tf, str(existing), True, 0, tuple(frame.columns), (*TIMESTAMP_INPUT_COLUMNS[:1], *REQUIRED_HISTORY_COLUMNS), False, "EMPTY_CSV", full_required=full_required, calibration_required=calibration_required)
    has_timestamp = any(column in frame.columns for column in TIMESTAMP_INPUT_COLUMNS)
    missing = tuple(column for column in REQUIRED_HISTORY_COLUMNS if column not in frame.columns)
    if not has_timestamp:
        missing = ("timestamp_utc", *missing)
    try:
        normalized = normalize_timestamps(frame)
    except Exception as exc:
        return _resolution(canonical, tf, str(existing), True, int(len(frame)), tuple(frame.columns), missing, False, f"TIMESTAMP_PARSE_ERROR: {exc}", full_required=full_required, calibration_required=calibration_required, timestamp_status="FAILED")
    diagnosis = normalized.diagnosis
    rows = int(diagnosis.get("rows_after", len(normalized.frame)) or 0)
    start_utc = pd.Timestamp(normalized.frame["timestamp_utc"].iloc[0]).isoformat() if rows else ""
    end_utc = pd.Timestamp(normalized.frame["timestamp_utc"].iloc[-1]).isoformat() if rows else ""
    duplicate_timestamps = int(diagnosis.get("duplicates", 0) or 0)
    ordered = bool(normalized.frame["timestamp_utc"].is_monotonic_increasing) if rows else True
    timestamp_status = str(diagnosis.get("status") or "")
    if timestamp_status == "FAILED":
        return _resolution(canonical, tf, str(existing), True, rows, tuple(frame.columns), missing, False, "TIMESTAMP_PARSE_ERROR", start_utc, end_utc, duplicate_timestamps, ordered, "spread" in frame.columns, str(diagnosis.get("timestamp_source_column") or ""), timestamp_status, start_utc, end_utc, full_required, calibration_required)
    if missing:
        return _resolution(canonical, tf, str(existing), True, rows, tuple(frame.columns), missing, False, "MISSING_REQUIRED_COLUMNS", start_utc, end_utc, duplicate_timestamps, ordered, "spread" in frame.columns, str(diagnosis.get("timestamp_source_column") or ""), timestamp_status, start_utc, end_utc, full_required, calibration_required)
    if rows < required_bars:
        return _resolution(canonical, tf, str(existing), True, rows, tuple(frame.columns), (), False, f"INSUFFICIENT_{tf}_BARS", start_utc, end_utc, duplicate_timestamps, ordered, "spread" in frame.columns, str(diagnosis.get("timestamp_source_column") or ""), timestamp_status, start_utc, end_utc, full_required, calibration_required)
    return _resolution(canonical, tf, str(existing), True, rows, tuple(frame.columns), (), True, None, start_utc, end_utc, duplicate_timestamps, ordered, "spread" in frame.columns, str(diagnosis.get("timestamp_source_column") or ""), timestamp_status, start_utc, end_utc, full_required, calibration_required)


def audit_historical_data(
    *,
    data_dir: str | Path,
    report_dir: str | Path,
    symbols: Iterable[str],
    timeframes: Iterable[str] = ("M5", "M15", "H1"),
    mode: str = "full",
) -> dict[str, Any]:
    """Write a historical data audit for all requested symbol/timeframe pairs."""

    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    minimums = CALIBRATION_MIN_BARS if mode == "calibration" else FULL_VALIDATION_MIN_BARS
    rows = [
        resolve_historical_data(
            data_dir,
            symbol=str(symbol).strip().upper(),
            timeframe=str(timeframe).strip().upper(),
            min_bars=minimums.get(str(timeframe).strip().upper(), 0),
        ).to_dict()
        for symbol in symbols
        for timeframe in timeframes
        if str(symbol).strip() and str(timeframe).strip()
    ]
    missing = [row for row in rows if not row["found"] or row["reason"]]
    critical = [row for row in rows if str(row.get("reason", "")).startswith("MISSING") or str(row.get("reason", "")).startswith("CSV_PARSE") or row.get("reason") == "EMPTY_CSV"]
    classification = "OK" if not missing else ("DATA_PARTIAL_BUT_USABLE_FOR_CALIBRATION" if mode == "calibration" and not critical else "NEEDS_MORE_DATA")
    timestamp_status = "OK" if rows and all(str(row.get("timestamp_status") or "") in {"OK", "WARNING"} for row in rows if row.get("found")) else "FAILED"
    h1_rows = [row for row in rows if row.get("timeframe") == "H1"]
    h1_bars_status = "OK" if h1_rows and all(bool(row.get("sufficient_for_full_validation")) for row in h1_rows) else ("CALIBRATION_ONLY" if h1_rows and all(bool(row.get("sufficient_for_calibration")) for row in h1_rows) else "INSUFFICIENT")
    summary = {
        "mode": "historical-data-audit",
        "classification": classification,
        "historical_data_status": classification,
        "timestamp_status": timestamp_status,
        "h1_bars_status": h1_bars_status,
        "files_checked": len(rows),
        "files_found": sum(1 for row in rows if row["found"]),
        "missing_timeframes": [row for row in rows if not row["found"]],
        "insufficient_timeframes": [row for row in rows if str(row.get("reason", "")).startswith("INSUFFICIENT")],
        "main_data_blocker": _main_blocker(missing),
        "reports_created": [
            str(output / "historical_data_audit.json"),
            str(output / "historical_data_audit.csv"),
            str(output / "missing_data.csv"),
            str(output / "report.html"),
        ],
        "execution_attempted": False,
    }
    (output / "historical_data_audit.json").write_text(json.dumps(_jsonable({**summary, "files": rows}), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(output / "historical_data_audit.csv", rows)
    _write_csv(output / "missing_data.csv", missing)
    (output / "report.html").write_text("<html><body><h1>Historical Data Audit</h1><pre>" + json.dumps(_jsonable(summary), indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return summary


def _candidate_paths(root: Path, symbol: str, timeframe: str, *, broker_symbol: str | None = None) -> tuple[Path, ...]:
    symbols = tuple(dict.fromkeys(item for item in (symbol, (broker_symbol or "").strip().upper()) if item))
    paths: list[Path] = []
    for value in symbols:
        paths.extend(
            [
                root / f"{value}_{timeframe}.csv",
                root / f"{value}-{timeframe}.csv",
                root / f"{value}_{timeframe}_rates.csv",
                root / f"{value}__{timeframe}.csv",
                root / timeframe / f"{value}.csv",
                root / value / f"{timeframe}.csv",
            ]
        )
    return tuple(paths)


def _main_blocker(rows: Iterable[Mapping[str, Any]]) -> str:
    for row in rows:
        reason = str(row.get("reason") or "")
        if reason:
            return reason
    return ""


def _resolution(
    symbol: str,
    timeframe: str,
    path: str,
    found: bool,
    rows: int,
    columns: tuple[str, ...],
    missing_columns: tuple[str, ...],
    is_sufficient: bool,
    reason: str | None,
    start_utc: str = "",
    end_utc: str = "",
    duplicate_timestamps: int = 0,
    timestamps_ordered: bool = True,
    has_spread: bool = False,
    timestamp_source_column: str = "",
    timestamp_status: str = "",
    timestamp_min: str = "",
    timestamp_max: str = "",
    full_required: int = 0,
    calibration_required: int = 0,
) -> HistoricalDataResolution:
    return HistoricalDataResolution(
        symbol=symbol,
        timeframe=timeframe,
        path=path,
        found=found,
        rows=rows,
        columns=columns,
        missing_columns=missing_columns,
        is_sufficient=is_sufficient,
        reason=reason,
        start_utc=start_utc,
        end_utc=end_utc,
        duplicate_timestamps=duplicate_timestamps,
        timestamps_ordered=timestamps_ordered,
        has_spread=has_spread,
        timestamp_source_column=timestamp_source_column,
        timestamp_status=timestamp_status or ("OK" if found and not reason else ""),
        timestamp_min=timestamp_min,
        timestamp_max=timestamp_max,
        timeframe_detected=timeframe,
        required_rows_full_validation=full_required,
        required_rows_calibration=calibration_required,
        sufficient_for_full_validation=rows >= full_required if full_required else True,
        sufficient_for_calibration=rows >= calibration_required if calibration_required else True,
    )


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["symbol", "timeframe", "reason"]
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
