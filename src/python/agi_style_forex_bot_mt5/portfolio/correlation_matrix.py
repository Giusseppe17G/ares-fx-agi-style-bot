"""Correlation matrix utilities from historical CSV closes."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

import pandas as pd

from ..data_pipeline.timestamp_normalizer import normalize_timestamps


# Fewer timestamp-aligned returns than this give no correlation (fail closed).
MIN_ALIGNED_RETURNS = 30


def compute_correlation_matrix(data_dir: str | Path, *, timeframe: str = "M5", window: int = 300) -> dict[str, Any]:
    directory = Path(data_dir)
    closes: dict[str, pd.Series] = {}
    for path in directory.glob(f"*_{timeframe}.csv"):
        symbol = path.stem.replace(f"_{timeframe}", "").upper()
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        if "close" not in frame.columns:
            continue
        # Index closes by bar time; a file without parseable times cannot be aligned.
        stamped = normalize_timestamps(frame)
        if stamped.diagnosis["status"] == "FAILED":
            closes[symbol] = pd.Series(dtype=float)
            continue
        closes[symbol] = pd.Series(stamped.frame["close"].astype(float).to_numpy(), index=stamped.frame["timestamp_utc"]).tail(window)
    if len(closes) < 2:
        return {"matrix": {}, "highly_correlated_pairs": [], "insufficient_overlap_pairs": [], "clusters": [], "classification": "WATCHLIST", "execution_attempted": False}
    symbols = sorted(closes)
    matrix: dict[str, dict[str, float | None]] = {symbol: {} for symbol in symbols}
    pairs = []
    insufficient = []
    for left in symbols:
        for right in symbols:
            if left > right:
                matrix[left][right] = matrix[right][left]
                continue
            value, aligned = _aligned_correlation(closes[left], closes[right])
            matrix[left][right] = value
            if left == right:
                continue
            if value is None:
                insufficient.append({"symbol_a": left, "symbol_b": right, "aligned_returns": aligned})
            elif abs(value) > 0.85:
                pairs.append({"symbol_a": left, "symbol_b": right, "correlation": value})
    classification = "OK" if not pairs and not insufficient else "WATCHLIST"
    return {"matrix": matrix, "highly_correlated_pairs": pairs, "insufficient_overlap_pairs": insufficient, "clusters": _clusters(pairs), "classification": classification, "min_aligned_returns": MIN_ALIGNED_RETURNS, "execution_attempted": False}


def build_correlation_report(*, data_dir: str | Path, output_dir: str | Path, timeframe: str = "M5", window: int = 300) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report = compute_correlation_matrix(data_dir, timeframe=timeframe, window=window)
    matrix_path = output / "correlation_matrix.csv"
    cluster_path = output / "correlation_clusters.csv"
    html_path = output / "report.html"
    _write_matrix(matrix_path, report["matrix"])
    _write_rows(cluster_path, report["highly_correlated_pairs"])
    html_path.write_text("<html><body><h1>Correlation Report</h1><pre>" + str(report) + "</pre></body></html>", encoding="utf-8")
    return {
        "mode": "correlation-report",
        "portfolio_risk_pct": 0.0,
        "currency_exposure": {},
        "concentration_flags": report["highly_correlated_pairs"],
        "reports_created": [str(matrix_path), str(cluster_path), str(html_path)],
        "correlation": report,
        "execution_attempted": False,
    }


def _aligned_correlation(left: pd.Series, right: pd.Series) -> tuple[float | None, int]:
    """Pearson correlation of returns on shared bar times only, or None."""

    joined = pd.concat([left, right], axis=1, join="inner").sort_index()
    # Returns are taken after the join so both legs span the same interval.
    returns = joined.pct_change(fill_method=None).dropna()
    if len(returns) < MIN_ALIGNED_RETURNS:
        return None, int(len(returns))
    value = float(returns.corr().iloc[0, 1])
    return (value if math.isfinite(value) else None), int(len(returns))


def _clusters(pairs: list[dict[str, Any]]) -> list[list[str]]:
    clusters: list[set[str]] = []
    for pair in pairs:
        symbols = {pair["symbol_a"], pair["symbol_b"]}
        merged = False
        for cluster in clusters:
            if cluster & symbols:
                cluster.update(symbols)
                merged = True
                break
        if not merged:
            clusters.append(set(symbols))
    return [sorted(cluster) for cluster in clusters]


def _write_matrix(path: Path, matrix: dict[str, dict[str, float]]) -> None:
    symbols = sorted(matrix)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", *symbols])
        for symbol in symbols:
            writer.writerow([symbol, *[matrix[symbol].get(other, 0.0) for other in symbols]])


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = ["symbol_a", "symbol_b", "correlation"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
