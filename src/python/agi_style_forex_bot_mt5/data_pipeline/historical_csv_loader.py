"""Single normalized historical CSV loader for research modules."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from ..data import add_indicators, add_regime_labels
from .historical_data_resolver import CALIBRATION_MIN_BARS, resolve_historical_data
from .timestamp_normalizer import normalize_timestamps
from .live_data_contract import normalize_ohlcv_contract


REQUIRED_CONTRACT_COLUMNS = (
    "timestamp_utc",
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)
OHLC_COLUMNS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class HistoricalCSVLoadResult:
    """Normalized historical CSV frame plus diagnostics."""

    frame: pd.DataFrame
    diagnostics: dict[str, Any]


def load_historical_csv_contract(path: str | Path, *, symbol: str = "", timeframe: str = "") -> HistoricalCSVLoadResult:
    """Read a CSV and return the project's canonical historical DataFrame."""

    csv_path = Path(path)
    if not csv_path.exists():
        return HistoricalCSVLoadResult(pd.DataFrame(columns=REQUIRED_CONTRACT_COLUMNS), _diagnostics(csv_path, "CSV_FILE_NOT_FOUND", symbol=symbol, timeframe=timeframe))
    try:
        raw = pd.read_csv(csv_path, encoding="utf-8-sig", sep=",")
    except Exception as exc:
        return HistoricalCSVLoadResult(pd.DataFrame(columns=REQUIRED_CONTRACT_COLUMNS), _diagnostics(csv_path, "CSV_READ_ERROR", symbol=symbol, timeframe=timeframe, error_message=str(exc)))
    columns_before = tuple(str(column) for column in raw.columns)
    if raw.empty:
        return HistoricalCSVLoadResult(pd.DataFrame(columns=REQUIRED_CONTRACT_COLUMNS), _diagnostics(csv_path, "CSV_EMPTY", symbol=symbol, timeframe=timeframe, columns_before=columns_before))
    common = normalize_ohlcv_contract(raw, source="historical", symbol=symbol, timeframe=timeframe, min_rows=0)
    if common.diagnostics["status"] == "OK":
        return HistoricalCSVLoadResult(common.frame, _diagnostics(csv_path, "OK", symbol=symbol, timeframe=timeframe, columns_before=columns_before, columns_after=tuple(common.frame.columns), rows_before=int(len(raw)), rows_after=int(len(common.frame)), timestamp_diagnostics={"status": "OK", "timestamp_source_column": common.diagnostics.get("timestamp_source_column", "timestamp_utc")}, warnings=common.diagnostics.get("blockers", ()), duplicates=int(common.diagnostics.get("duplicate_timestamps", 0) or 0)))
    frame = _normalize_columns(raw)
    missing_ohlc = tuple(column for column in OHLC_COLUMNS if column not in frame.columns)
    if missing_ohlc:
        return HistoricalCSVLoadResult(frame, _diagnostics(csv_path, "CSV_MISSING_OHLC", symbol=symbol, timeframe=timeframe, columns_before=columns_before, columns_after=tuple(frame.columns), missing_columns=missing_ohlc))
    timestamps = normalize_timestamps(frame)
    if timestamps.diagnosis["status"] == "FAILED":
        return HistoricalCSVLoadResult(frame, _diagnostics(csv_path, "CSV_TIMESTAMP_PARSE_ERROR", symbol=symbol, timeframe=timeframe, columns_before=columns_before, columns_after=tuple(frame.columns), timestamp_diagnostics=timestamps.diagnosis))
    frame = timestamps.frame.copy()
    frame["time"] = frame["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    warnings: list[str] = []
    numeric_columns = ["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
    if "tick_volume" not in frame.columns and "volume" in frame.columns:
        frame["tick_volume"] = frame["volume"]
    if "spread" not in frame.columns:
        frame["spread"] = 0
        warnings.append("CSV_SPREAD_MISSING_ASSUMED_ZERO")
    if "real_volume" not in frame.columns:
        frame["real_volume"] = 0
    numeric_error = _coerce_numeric(frame, numeric_columns)
    if numeric_error:
        return HistoricalCSVLoadResult(frame, _diagnostics(csv_path, "CSV_NUMERIC_CONVERSION_ERROR", symbol=symbol, timeframe=timeframe, columns_before=columns_before, columns_after=tuple(frame.columns), error_message=numeric_error, warnings=warnings))
    duplicates = int(timestamps.diagnosis.get("duplicates", 0) or 0)
    if duplicates:
        warnings.append("CSV_DUPLICATE_TIMESTAMPS")
    if timestamps.diagnosis.get("reason") == "TIMESTAMP_NORMALIZED_WITH_DROPS":
        warnings.append("CSV_UNSORTED_FIXED")
    for column in REQUIRED_CONTRACT_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0 if column in {"spread", "real_volume"} else ""
    frame = frame.loc[:, list(REQUIRED_CONTRACT_COLUMNS) + [column for column in frame.columns if column not in REQUIRED_CONTRACT_COLUMNS]]
    diagnostics = _diagnostics(
        csv_path,
        "OK",
        symbol=symbol,
        timeframe=timeframe,
        columns_before=columns_before,
        columns_after=tuple(frame.columns),
        rows_before=int(len(raw)),
        rows_after=int(len(frame)),
        timestamp_diagnostics=timestamps.diagnosis,
        warnings=warnings,
        duplicates=duplicates,
    )
    return HistoricalCSVLoadResult(frame, diagnostics)


def build_strategy_data_contract_report(
    *,
    data_dir: str | Path,
    report_dir: str | Path,
    symbols: Iterable[str],
    timeframes: Iterable[str] = ("M5", "M15", "H1"),
) -> dict[str, Any]:
    """Audit whether normalized historical frames are ready for strategies."""

    output = Path(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for symbol in [str(item).strip().upper() for item in symbols if str(item).strip()]:
        for timeframe in [str(item).strip().upper() for item in timeframes if str(item).strip()]:
            resolution = resolve_historical_data(data_dir, symbol=symbol, timeframe=timeframe, min_bars=CALIBRATION_MIN_BARS.get(timeframe, 0))
            if not resolution.found:
                rows.append(_contract_row(symbol, timeframe, resolution.path, False, resolution.reason or "CSV_FILE_NOT_FOUND"))
                continue
            loaded = load_historical_csv_contract(resolution.path, symbol=symbol, timeframe=timeframe)
            diagnostics = loaded.diagnostics
            feature_ok = False
            blockers = list(diagnostics.get("warnings", []))
            if diagnostics["status"] == "OK":
                try:
                    from ..market_structure import build_market_structure_features

                    feature_frame = loaded.frame.rename(columns={"spread": "spread_points"}).copy()
                    feature_frame["volume"] = feature_frame["tick_volume"]
                    enriched = add_regime_labels(add_indicators(feature_frame))
                    if timeframe == "M5":
                        build_market_structure_features(loaded.frame)
                    feature_ok = not enriched.empty
                except Exception as exc:
                    blockers.append(f"FEATURE_BUILD_ERROR: {exc}")
            else:
                blockers.append(str(diagnostics["status"]))
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "path": resolution.path,
                    "file_found": True,
                    "rows": diagnostics.get("rows_after", 0),
                    "columns_before": "|".join(diagnostics.get("columns_before", [])),
                    "columns_after": "|".join(diagnostics.get("columns_after", [])),
                    "numeric_ohlc_ok": diagnostics["status"] == "OK",
                    "timestamp_ok": str(diagnostics.get("timestamp_status", "")) in {"OK", "WARNING"},
                    "required_contract_ok": diagnostics["status"] == "OK",
                    "feature_build_ok": feature_ok,
                    "strategy_input_ready": diagnostics["status"] == "OK" and feature_ok,
                    "blockers": "|".join(blockers),
                    "execution_attempted": False,
                }
            )
    status = "OK" if rows and all(row["strategy_input_ready"] for row in rows if row["timeframe"] == "M5") else "NEEDS_MORE_DATA"
    summary = {
        "mode": "strategy-data-contract",
        "classification": status,
        "data_contract_status": status,
        "data_valid_symbols": sorted({row["symbol"] for row in rows if row["required_contract_ok"]}),
        "strategy_input_ready_symbols": sorted({row["symbol"] for row in rows if row["strategy_input_ready"]}),
        "csv_blockers": _top_blockers(rows),
        "reports_created": [str(output / "data_contract_report.json"), str(output / "data_contract_report.csv"), str(output / "report.html")],
        "execution_attempted": False,
    }
    (output / "data_contract_report.json").write_text(json.dumps(_jsonable({**summary, "rows": rows}), indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(output / "data_contract_report.csv", rows)
    (output / "report.html").write_text("<html><body><h1>Strategy Data Contract</h1><pre>" + json.dumps(_jsonable(summary), indent=2, sort_keys=True) + "</pre></body></html>", encoding="utf-8")
    return summary


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized.columns = [str(column).strip().strip("\ufeff").lower() for column in normalized.columns]
    aliases = {
        "volume": "tick_volume",
        "real_volume": "real_volume",
        "spread": "spread",
    }
    for source, target in aliases.items():
        if source in normalized.columns and target not in normalized.columns:
            normalized[target] = normalized[source]
    return normalized


def _coerce_numeric(frame: pd.DataFrame, columns: Iterable[str]) -> str:
    for column in columns:
        if column not in frame.columns:
            continue
        converted = pd.to_numeric(frame[column], errors="coerce")
        if converted.isna().any():
            return f"{column} contains non-numeric values"
        frame[column] = converted
    return ""


def _diagnostics(
    path: Path,
    status: str,
    *,
    symbol: str,
    timeframe: str,
    columns_before: Iterable[str] = (),
    columns_after: Iterable[str] = (),
    rows_before: int = 0,
    rows_after: int = 0,
    missing_columns: Iterable[str] = (),
    timestamp_diagnostics: Mapping[str, Any] | None = None,
    error_message: str = "",
    warnings: Iterable[str] = (),
    duplicates: int = 0,
) -> dict[str, Any]:
    timestamp = dict(timestamp_diagnostics or {})
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "path": str(path),
        "status": status,
        "error_message": error_message,
        "columns_before": tuple(columns_before),
        "columns_after": tuple(columns_after),
        "missing_columns": tuple(missing_columns),
        "rows_before": rows_before,
        "rows_after": rows_after,
        "duplicates": duplicates,
        "warnings": tuple(warnings),
        "timestamp_status": timestamp.get("status", ""),
        "timestamp_source_column": timestamp.get("timestamp_source_column", ""),
        "execution_attempted": False,
    }


def _contract_row(symbol: str, timeframe: str, path: str, found: bool, blocker: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "path": path,
        "file_found": found,
        "rows": 0,
        "columns_before": "",
        "columns_after": "",
        "numeric_ohlc_ok": False,
        "timestamp_ok": False,
        "required_contract_ok": False,
        "feature_build_ok": False,
        "strategy_input_ready": False,
        "blockers": blocker,
        "execution_attempted": False,
    }


def _top_blockers(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        for blocker in str(row.get("blockers") or "").split("|"):
            if blocker:
                counts[blocker] = counts.get(blocker, 0) + 1
    return [{"blocker": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["symbol", "timeframe", "blockers"]
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
