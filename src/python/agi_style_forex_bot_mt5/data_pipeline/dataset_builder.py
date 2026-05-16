"""Dataset manifest builder for historical backtesting inputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .history_quality import scan_history_directory


def build_dataset_manifest(
    *,
    data_dir: str | Path,
    report_dir: str | Path,
    symbols: Iterable[str] | None = None,
    timeframes: Iterable[str] = ("M5", "M15", "H1"),
) -> dict[str, Any]:
    """Validate historical files and write dataset manifest reports."""

    return scan_history_directory(
        data_dir,
        report_dir=report_dir,
        symbols=symbols,
        timeframes=timeframes,
    )
