"""Exposure risk audit."""

from __future__ import annotations

from typing import Any, Mapping

from .cooldown_risk_audit import _audit_reason


def audit_exposure_risk(extracted: Mapping[str, Any]) -> dict[str, Any]:
    return _audit_reason("EXPOSURE_BLOCK", extracted)
