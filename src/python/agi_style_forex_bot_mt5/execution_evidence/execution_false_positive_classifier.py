"""Helpers for separating safe execution mentions from blocking evidence."""

from __future__ import annotations

from typing import Any, Mapping

from .order_call_scanner import BLOCKING_CLASSES, SAFE_CLASSES


def is_blocking_execution_finding(finding: Mapping[str, Any]) -> bool:
    return str(finding.get("classification")) in BLOCKING_CLASSES


def is_false_positive_execution_finding(finding: Mapping[str, Any]) -> bool:
    return str(finding.get("classification")) in SAFE_CLASSES
