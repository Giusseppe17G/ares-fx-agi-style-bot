"""Paper risk state context for Micro V2 risk block audit."""

from __future__ import annotations

from typing import Any, Mapping


def audit_paper_risk_state(filter_analysis: Mapping[str, Any], checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "filter_analysis_status": filter_analysis.get("micro_v2_filter_analysis_status", ""),
        "filter_analysis_dominant_filter": filter_analysis.get("dominant_v2_filter", ""),
        "checkpoint_status": checkpoint.get("micro_v2_checkpoint_status", ""),
        "v2_paper_trades_open": checkpoint.get("v2_paper_trades_open", 0),
        "v2_paper_trades_closed": checkpoint.get("v2_paper_trades_closed", 0),
        "paper_state_recovery_status": checkpoint.get("paper_state_recovery_status", ""),
        "config_error_root_cause": checkpoint.get("config_error_root_cause", ""),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
