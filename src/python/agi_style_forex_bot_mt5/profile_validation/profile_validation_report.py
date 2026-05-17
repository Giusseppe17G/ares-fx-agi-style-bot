"""Profile validation report helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .balanced_candidate_gate import run_balanced_candidate_gate
from .profile_integrity_checker import run_profile_integrity


def write_profile_validation_report(
    *,
    runs_root: str | Path,
    profile_runs_dir: str | Path,
    edge_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Run profile integrity and BALANCED gate in one call."""

    integrity = run_profile_integrity(profile_runs_dir=profile_runs_dir, output_dir=output_dir)
    gate = run_balanced_candidate_gate(runs_root=runs_root, profile_runs_dir=profile_runs_dir, edge_dir=edge_dir, output_dir=output_dir)
    return {
        "mode": "profile-validation-report",
        "profile_integrity_status": integrity.get("profile_integrity_status", ""),
        "balanced_decision": gate.get("balanced_decision", ""),
        "execution_attempted": False,
        "reports_created": [*integrity.get("reports_created", []), *gate.get("reports_created", [])],
    }
