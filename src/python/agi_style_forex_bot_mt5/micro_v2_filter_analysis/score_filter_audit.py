"""Score threshold filter audit."""

from __future__ import annotations

from typing import Any, Mapping

from .regime_filter_audit import _audit_filter


def audit_score_filter(breakdown: Mapping[str, Any]) -> dict[str, Any]:
    return _audit_filter("SCORE_THRESHOLD_BLOCK", breakdown)
