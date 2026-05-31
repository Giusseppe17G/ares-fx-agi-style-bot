"""Existing acceptance snapshot loader for Micro V2 checkpoints."""

from __future__ import annotations

from typing import Any, Mapping


def build_acceptance_snapshot(existing_acceptance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "forward_acceptance_v2_decision": existing_acceptance.get("decision", ""),
        "forward_acceptance_v2_classification": existing_acceptance.get("classification", ""),
        "forward_acceptance_v2_reason": existing_acceptance.get("reason", ""),
        "acceptance_snapshot_available": bool(existing_acceptance),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
