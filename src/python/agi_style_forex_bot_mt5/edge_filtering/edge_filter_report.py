"""CLI-facing helpers for edge filtering reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .filtered_profile_builder import build_filtered_profile


def run_edge_filtering(
    *,
    runs_root: str | Path = "data/runs",
    edge_dir: str | Path = "data/reports/edge",
    output_dir: str | Path = "data/reports/edge_filtering",
    base_profile: str = "BALANCED",
) -> dict[str, Any]:
    """Run edge filtering and write BALANCED_FILTERED artifacts."""

    return build_filtered_profile(runs_root=runs_root, edge_dir=edge_dir, output_dir=output_dir, base_profile=base_profile)


def run_filtered_profile_builder(
    *,
    runs_root: str | Path = "data/runs",
    edge_dir: str | Path = "data/reports/edge",
    output_dir: str | Path = "data/reports/edge_filtering",
    base_profile: str = "BALANCED",
) -> dict[str, Any]:
    """Alias for explicit build-filtered-profile CLI mode."""

    summary = build_filtered_profile(runs_root=runs_root, edge_dir=edge_dir, output_dir=output_dir, base_profile=base_profile)
    return {**summary, "mode": "build-filtered-profile"}
