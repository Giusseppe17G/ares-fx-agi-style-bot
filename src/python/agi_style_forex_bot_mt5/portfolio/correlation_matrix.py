"""Correlation matrix utilities from historical CSV closes."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd


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
        closes[symbol] = pd.Series(frame["close"].astype(float).tail(window).pct_change().dropna().reset_index(drop=True))
    if len(closes) < 2:
        return {"matrix": {}, "highly_correlated_pairs": [], "clusters": [], "classification": "WATCHLIST", "execution_attempted": False}
    data = pd.DataFrame(closes).dropna()
    corr = data.corr().fillna(0.0)
    matrix = {row: {col: float(corr.loc[row, col]) for col in corr.columns} for row in corr.index}
    pairs = []
    for left in corr.columns:
        for right in corr.columns:
            if left >= right:
                continue
            value = float(corr.loc[left, right])
            if abs(value) > 0.85:
                pairs.append({"symbol_a": left, "symbol_b": right, "correlation": value})
    return {"matrix": matrix, "highly_correlated_pairs": pairs, "clusters": _clusters(pairs), "classification": "OK" if not pairs else "WATCHLIST", "execution_attempted": False}


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
