"""Build a separate safe BALANCED_STABLE_MICRO_V2 profile."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping


def build_micro_v2_profile(candidate: Mapping[str, str], *, output_path: str | Path) -> dict[str, object]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {str(key).upper(): str(value) for key, value in candidate.items() if str(key).upper() != "NOT_ACTIVE_RESEARCH_ONLY"}
    values.update(
        {
            "PROFILE_NAME": "BALANCED_STABLE_MICRO_V2",
            "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO_V2",
            "PAPER_ONLY": "true",
            "NOT_FOR_DEMO_LIVE": "true",
            "REQUIRES_STABLE_GATE": "true",
            "REQUIRES_PAPER_RISK_CLEARANCE": "true",
            "REQUIRES_DAILY_RISK_LEDGER": "true",
            "CREATED_FROM": "balanced_stable_micro_v2_candidate.ini",
            "APPROVED_FOR_PAPER_DRY_RUN_ONLY": "true",
            "NOT_FOR_LIVE": "true",
            "EXECUTION_ATTEMPTED": "false",
        }
    )
    lines = [f"{key}={values[key]}" for key in sorted(values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "micro_v2_profile_created": True,
        "micro_v2_profile_path": str(path),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def build_micro_v2_profile_from_proposed(candidate: Mapping[str, str], *, output_path: str | Path) -> dict[str, object]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        str(key).upper(): str(value)
        for key, value in candidate.items()
        if str(key).upper() not in {"NOT_ACTIVE_RESEARCH_ONLY", "APPROVED_FOR_PAPER_DRY_RUN_ONLY", "PROFILE_NAME"}
    }
    values.update(
        {
            "PROFILE_NAME": "BALANCED_STABLE_MICRO_V2",
            "SIGNAL_PROFILE": "BALANCED_STABLE_MICRO_V2",
            "PAPER_ONLY": "true",
            "NOT_FOR_DEMO_LIVE": "true",
            "NOT_FOR_LIVE": "true",
            "REQUIRES_STABLE_GATE": "true",
            "REQUIRES_PAPER_RISK_CLEARANCE": "true",
            "REQUIRES_DAILY_RISK_LEDGER": "true",
            "CREATED_FROM": "balanced_stable_micro_v2_proposed.ini",
            "SOURCE_PHASE": "FASE_48_MICRO_V2_PROPOSED_REVIEW",
            "APPROVED_FOR_PAPER_DRY_RUN_ONLY": "true",
            "APPROVED_FOR_DEMO": "false",
            "APPROVED_FOR_LIVE": "false",
            "EXECUTION_ATTEMPTED": "false",
        }
    )
    lines = [f"{key}={values[key]}" for key in sorted(values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "micro_v2_profile_created": True,
        "micro_v2_profile_path": str(path),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
