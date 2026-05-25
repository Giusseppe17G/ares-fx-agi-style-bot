"""Evidence window helpers for telemetry acceptance."""

from __future__ import annotations

from typing import Any, Mapping


def latest_clean_window_start(context: Mapping[str, Any]) -> str:
    return str(context.get("latest_clean_window_start_utc") or "")


def telemetry_acceptance_window_summary(context: Mapping[str, Any], summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "latest_clean_window_start_utc": latest_clean_window_start(context),
        "latest_reset_utc": context.get("latest_reset_utc"),
        "active_telemetry_blocking_count": summary.get("active_blocking_count", 0),
        "historical_telemetry_issue_count": summary.get("historical_invalid_count", 0),
        "telemetry_quarantined_count": summary.get("quarantined_count", 0),
        "historical_telemetry_quarantined_count": summary.get("historical_quarantined_count", summary.get("quarantined_count", 0)),
        "historical_telemetry_reviewed_count": summary.get("historical_reviewed_count", summary.get("reviewed_count", 0)),
        "historical_telemetry_unreviewed_count": summary.get("historical_unreviewed_count", summary.get("unquarantined_historical_count", 0)),
        "telemetry_acceptance_clear": summary.get("telemetry_acceptance_clear", False),
        "telemetry_policy_reason": summary.get("telemetry_policy_reason", ""),
        "execution_attempted": False,
    }
