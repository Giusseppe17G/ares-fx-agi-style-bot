"""Timestamp normalization for MT5-exported historical CSV data."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


TIMESTAMP_COLUMNS = ("timestamp_utc", "timestamp", "datetime", "date", "time")


@dataclass(frozen=True)
class TimestampNormalizationResult:
    """Normalized frame plus audit diagnostics."""

    frame: pd.DataFrame
    diagnosis: dict[str, Any]


def normalize_timestamps(frame: pd.DataFrame) -> TimestampNormalizationResult:
    """Return a frame with sorted, UTC-aware `timestamp_utc`."""

    rows_before = int(len(frame))
    data = frame.copy()
    source = _source_column(data)
    if source is None:
        return TimestampNormalizationResult(
            data,
            {
                "timestamp_source_column": "",
                "rows_before": rows_before,
                "rows_after": rows_before,
                "null_timestamps": rows_before,
                "duplicates": 0,
                "timezone_assumed": "UTC",
                "status": "FAILED",
                "reason": "TIMESTAMP_PARSE_ERROR",
            },
        )
    parsed = _parse_timestamp_series(data, source)
    nulls = int(parsed.isna().sum())
    data["timestamp_utc"] = parsed
    data = data[data["timestamp_utc"].notna()].copy()
    duplicates = int(data["timestamp_utc"].duplicated().sum())
    data = data.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last").reset_index(drop=True)
    status = "OK"
    reason = None
    if data.empty:
        status = "FAILED"
        reason = "TIMESTAMP_PARSE_ERROR"
    elif nulls or duplicates:
        status = "WARNING"
        reason = "TIMESTAMP_NORMALIZED_WITH_DROPS"
    return TimestampNormalizationResult(
        data,
        {
            "timestamp_source_column": source,
            "rows_before": rows_before,
            "rows_after": int(len(data)),
            "null_timestamps": nulls,
            "duplicates": duplicates,
            "timezone_assumed": "UTC",
            "status": status,
            "reason": reason,
        },
    )


def audit_timestamps(
    *,
    data_dir: str | Path,
    report_dir: str | Path,
    symbols: Iterable[str],
    timeframes: Iterable[str] = ("M5", "M15", "H1"),
) -> dict[str, Any]:
    """Write timestamp audit reports for configured historical files."""

    from .historical_data_resolver import resolve_historical_data

    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for symbol in [str(item).strip().upper() for item in symbols if str(item).strip()]:
        for timeframe in [str(item).strip().upper() for item in timeframes if str(item).strip()]:
            resolution = resolve_historical_data(data_dir, symbol=symbol, timeframe=timeframe, min_bars=0)
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "path": resolution.path,
                    "found": resolution.found,
                    "timestamp_source_column": resolution.timestamp_source_column,
                    "timestamp_status": resolution.timestamp_status,
                    "timestamp_min": resolution.timestamp_min,
                    "timestamp_max": resolution.timestamp_max,
                    "rows": resolution.rows,
                    "reason": resolution.reason,
                    "execution_attempted": False,
                }
            )
    status = "OK" if rows and all(row["timestamp_status"] == "OK" for row in rows if row["found"]) else "WARNING"
    if not any(row["found"] for row in rows):
        status = "FAILED"
    summary = {
        "mode": "timestamp-audit",
        "classification": status,
        "timestamp_status": status,
        "rows_checked": len(rows),
        "reports_created": [str(output / "timestamp_audit.json"), str(output / "timestamp_audit.csv"), str(output / "report.html")],
        "execution_attempted": False,
    }
    (output / "timestamp_audit.json").write_text(json.dumps(_jsonable({**summary, "files": rows}), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(output / "timestamp_audit.csv", rows)
    (output / "report.html").write_text("<html><body><h1>Timestamp Audit</h1><pre>" + json.dumps(_jsonable(summary), indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return summary


def _source_column(frame: pd.DataFrame) -> str | None:
    columns = {str(column).strip().lower(): column for column in frame.columns}
    if "date" in columns and "time" in columns and "timestamp_utc" not in columns:
        frame["date_time"] = frame[columns["date"]].astype(str) + " " + frame[columns["time"]].astype(str)
        return "date_time"
    for name in TIMESTAMP_COLUMNS:
        if name in columns:
            return str(columns[name])
    return None


def _parse_timestamp_series(frame: pd.DataFrame, source: str) -> pd.Series:
    values = frame[source]
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() >= max(1, int(len(values) * 0.8)):
        median = float(numeric.dropna().abs().median()) if numeric.notna().any() else 0.0
        unit = "ms" if median > 10_000_000_000 else "s"
        return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(values, utc=True, errors="coerce")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["symbol", "timeframe", "timestamp_status"]
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
