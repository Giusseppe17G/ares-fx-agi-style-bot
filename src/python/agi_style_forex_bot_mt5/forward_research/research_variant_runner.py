"""Thin wrapper for research-only forward blocker variants."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .blocker_sensitivity import run_blocker_sensitivity


def run_research_variants(candidates: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate research-only variants without mutating forward-shadow state."""

    return run_blocker_sensitivity(candidates)
