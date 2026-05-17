"""Historical CSV quality checks for exported MT5 datasets."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .historical_csv_loader import load_historical_csv_contract
from .historical_data_resolver import resolve_historical_data


REQUIRED_COLUMNS = {"time", "open", "high", "low", "close", "tick_volume"}


@dataclass(frozen=True)
class HistoryQualityResult:
    """Quality summary for one symbol/timeframe CSV."""

    symbol: str
    timeframe: str
    file_path: str
    rows: int
    start_utc: str
    end_utc: str
    duplicate_timestamps: int
    gaps: int
    anomalies: int
    spread_extreme_count: int
    spread_p95: float | None
    spread_p99: float | None
    fingerprint: str
    quality_score: float
    classification: str


def load_history_csv(path: str | Path, *, symbol: str, timeframe: str) -> pd.DataFrame:
    """Load a MT5-exported CSV and normalize timestamps to UTC."""

    csv_path = Path(path)
    loaded = load_historical_csv_contract(csv_path, symbol=symbol, timeframe=timeframe)
    if loaded.diagnostics["status"] != "OK":
        raise ValueError(str(loaded.diagnostics["status"]))
    frame = loaded.frame.copy()
    frame["time"] = frame["timestamp_utc"]
    if frame[["open", "high", "low", "close", "tick_volume"]].isna().any().any():
        raise ValueError("historical CSV contains non-numeric OHLCV values")
    frame = frame.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)
    frame["symbol"] = symbol
    frame["timeframe"] = timeframe
    return frame


def evaluate_history_quality(
    path: str | Path,
    *,
    symbol: str,
    timeframe: str,
    max_spread_points: float = 50.0,
) -> tuple[HistoryQualityResult, pd.DataFrame, pd.DataFrame]:
    """Return quality result plus gap/anomaly detail frames."""

    csv_path = Path(path)
    raw = pd.read_csv(csv_path)
    duplicate_count = int(load_historical_csv_contract(csv_path, symbol=symbol, timeframe=timeframe).diagnostics.get("duplicates", 0) or 0)
    frame = load_history_csv(csv_path, symbol=symbol, timeframe=timeframe)
    expected_gap = timeframe_seconds(timeframe)
    gaps = _gap_frame(frame, expected_gap, symbol=symbol, timeframe=timeframe)
    anomalies = _anomaly_frame(frame, symbol=symbol, timeframe=timeframe, max_spread_points=max_spread_points)
    spread = frame["spread"].astype(float) if "spread" in frame.columns else pd.Series(dtype=float)
    spread_extreme_count = int((spread > max_spread_points).sum()) if len(spread) else 0
    penalty = duplicate_count * 2 + len(gaps) * 5 + len(anomalies) * 3 + spread_extreme_count * 2
    quality_score = max(0.0, min(100.0, 100.0 - penalty))
    classification = "OK" if quality_score >= 90 else ("WATCHLIST" if quality_score >= 70 else "REJECTED")
    result = HistoryQualityResult(
        symbol=symbol,
        timeframe=timeframe,
        file_path=str(csv_path),
        rows=len(frame),
        start_utc=pd.Timestamp(frame["time"].iloc[0]).isoformat(),
        end_utc=pd.Timestamp(frame["time"].iloc[-1]).isoformat(),
        duplicate_timestamps=duplicate_count,
        gaps=len(gaps),
        anomalies=len(anomalies),
        spread_extreme_count=spread_extreme_count,
        spread_p95=float(spread.quantile(0.95)) if len(spread) else None,
        spread_p99=float(spread.quantile(0.99)) if len(spread) else None,
        fingerprint=sha256(csv_path.read_bytes()).hexdigest(),
        quality_score=quality_score,
        classification=classification,
    )
    return result, gaps, anomalies


def scan_history_directory(
    data_dir: str | Path,
    *,
    report_dir: str | Path,
    symbols: Iterable[str] | None = None,
    timeframes: Iterable[str] = ("M5", "M15", "H1"),
) -> dict[str, Any]:
    """Scan historical CSVs and write quality reports."""

    data_path = Path(data_dir)
    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)
    selected_symbols = {item.strip().upper() for item in symbols or () if item.strip()}
    results: list[HistoryQualityResult] = []
    gap_frames: list[pd.DataFrame] = []
    anomaly_frames: list[pd.DataFrame] = []
    requested_timeframes = {tf.upper() for tf in timeframes}
    paths: list[tuple[Path, str, str]] = []
    if selected_symbols:
        for symbol in sorted(selected_symbols):
            for timeframe in sorted(requested_timeframes):
                resolution = resolve_historical_data(data_path, symbol=symbol, timeframe=timeframe, min_bars=0)
                if resolution.found and resolution.reason not in {"MISSING_REQUIRED_COLUMNS", "EMPTY_CSV"} and not str(resolution.reason or "").startswith("CSV_PARSE"):
                    paths.append((Path(resolution.path), symbol, timeframe))
    else:
        for csv_path in sorted(data_path.rglob("*.csv")):
            parsed = parse_history_filename(csv_path)
            if parsed is None:
                continue
            symbol, timeframe = parsed
            if timeframe not in requested_timeframes:
                continue
            paths.append((csv_path, symbol, timeframe))
    for csv_path, symbol, timeframe in paths:
        result, gaps, anomalies = evaluate_history_quality(csv_path, symbol=symbol, timeframe=timeframe)
        results.append(result)
        gap_frames.append(gaps)
        anomaly_frames.append(anomalies)
    if not results:
        raise ValueError(f"no historical CSV files found in {data_path}")
    by_symbol = pd.DataFrame([asdict(item) for item in results])
    gaps = pd.concat(gap_frames, ignore_index=True) if gap_frames else pd.DataFrame()
    anomalies = pd.concat(anomaly_frames, ignore_index=True) if anomaly_frames else pd.DataFrame()
    manifest = {
        "dataset_fingerprint": dataset_fingerprint(item.fingerprint for item in results),
        "files": [asdict(item) for item in results],
        "execution_attempted": False,
    }
    classification = _overall_classification(item.classification for item in results)
    summary = {
        "mode": "data-quality",
        "classification": classification,
        "files_scanned": len(results),
        "total_gaps": int(sum(item.gaps for item in results)),
        "total_anomalies": int(sum(item.anomalies for item in results)),
        "dataset_fingerprint": manifest["dataset_fingerprint"],
        "reports_created": [
            str(report_path / "summary.json"),
            str(report_path / "by_symbol_timeframe.csv"),
            str(report_path / "gaps.csv"),
            str(report_path / "anomalies.csv"),
            str(report_path / "dataset_manifest.json"),
        ],
        "execution_attempted": False,
    }
    (report_path / "summary.json").write_text(json.dumps(_jsonable(summary), indent=2, sort_keys=True), encoding="utf-8")
    by_symbol.to_csv(report_path / "by_symbol_timeframe.csv", index=False)
    gaps.to_csv(report_path / "gaps.csv", index=False)
    anomalies.to_csv(report_path / "anomalies.csv", index=False)
    (report_path / "dataset_manifest.json").write_text(json.dumps(_jsonable(manifest), indent=2, sort_keys=True), encoding="utf-8")
    return summary


def parse_history_filename(path: Path) -> tuple[str, str] | None:
    stem = path.stem.upper()
    parts = stem.replace("-", "_").split("_")
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def timeframe_seconds(timeframe: str) -> float:
    value = timeframe.upper()
    if value.startswith("M"):
        return float(value[1:]) * 60.0
    if value.startswith("H"):
        return float(value[1:]) * 3600.0
    if value.startswith("D"):
        return float(value[1:] or 1) * 86400.0
    return 300.0


def dataset_fingerprint(fingerprints: Iterable[str]) -> str:
    joined = "|".join(sorted(fingerprints))
    return sha256(joined.encode("utf-8")).hexdigest()


def _gap_frame(frame: pd.DataFrame, expected_gap: float, *, symbol: str, timeframe: str) -> pd.DataFrame:
    diffs = frame["time"].diff().dt.total_seconds()
    rows = []
    for index, seconds in diffs.items():
        if pd.notna(seconds) and seconds > expected_gap * 1.5:
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "gap_start": frame.loc[index - 1, "time"].isoformat(),
                    "gap_end": frame.loc[index, "time"].isoformat(),
                    "gap_seconds": float(seconds),
                    "expected_seconds": expected_gap,
                }
            )
    return pd.DataFrame(rows)


def _anomaly_frame(frame: pd.DataFrame, *, symbol: str, timeframe: str, max_spread_points: float) -> pd.DataFrame:
    rows = []
    for index, row in frame.iterrows():
        reason = ""
        if row["high"] < row["low"] or row["high"] < max(row["open"], row["close"]) or row["low"] > min(row["open"], row["close"]):
            reason = "invalid_ohlc"
        elif min(row["open"], row["high"], row["low"], row["close"]) <= 0:
            reason = "non_positive_price"
        elif "spread" in frame.columns and row.get("spread", 0) > max_spread_points:
            reason = "extreme_spread"
        if reason:
            rows.append({"symbol": symbol, "timeframe": timeframe, "time": row["time"].isoformat(), "reason": reason})
    return pd.DataFrame(rows)


def _overall_classification(values: Iterable[str]) -> str:
    labels = set(values)
    if "REJECTED" in labels:
        return "REJECTED"
    if "WATCHLIST" in labels:
        return "WATCHLIST"
    return "OK"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and (np.isinf(value) or np.isnan(value)):
        return None
    return value
