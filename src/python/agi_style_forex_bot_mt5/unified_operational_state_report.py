"""FASE 81 equivalence report: legacy halt detectors and relaunch gates vs the canonical core."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import Clock, FrozenClock, RunManifest, SafetyEnvelope, SystemClock, workspace_paths
from .core.operational_state.equivalence import (
    REFERENCE_NOW,
    build_equivalence_report,
    build_gate_equivalence_report,
)


def run_unified_operational_state_report(
    *,
    output_dir: str | Path | None = None,
    reference_time_utc: str = "",
) -> dict[str, Any]:
    paths = workspace_paths()
    clock = _clock(reference_time_utc)
    halt_report = build_equivalence_report(clock=clock)
    gate_report = build_gate_equivalence_report(clock=clock)
    manifest = RunManifest.build(mode="unified-operational-state", clock=clock, workspace=paths)

    output = Path(output_dir) if output_dir is not None else paths.reports_dir / "micro_v2_unified_operational_state"
    output.mkdir(parents=True, exist_ok=True)
    created = []
    for name, payload in (("halt_migration_diff.json", halt_report), ("relaunch_gate_migration_diff.json", gate_report)):
        target = output / name
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        created.append(str(target))

    summary = {
        "mode": "unified-operational-state",
        "unified_operational_state_status": (
            "UNIFIED_OPERATIONAL_STATE_OK"
            if halt_report["equivalence_status"] == "EQUIVALENCE_OK" and gate_report["gate_equivalence_status"] == "GATE_EQUIVALENCE_OK"
            else "UNIFIED_OPERATIONAL_STATE_DIFFERENCE"
        ),
        "halt_equivalence_status": halt_report["equivalence_status"],
        "halt_comparison_count": halt_report["comparison_count"],
        "halt_same_decision_count": halt_report["same_decision_count"],
        "halt_difference_count": halt_report["difference_count"],
        "halt_legacy_behavior_bug_count": halt_report["legacy_behavior_bug_count"],
        "halt_intentional_canonical_change_count": halt_report["intentional_canonical_change_count"],
        "halt_unexplained_difference_count": halt_report["unexplained_difference_count"],
        "gate_equivalence_status": gate_report["gate_equivalence_status"],
        "gate_comparison_count": gate_report["comparison_count"],
        "gate_same_decision_count": gate_report["same_decision_count"],
        "gate_difference_count": gate_report["difference_count"],
        "reports_created": created,
    }
    return manifest.attach(SafetyEnvelope().seal(summary, full=True))


def _clock(reference_time_utc: str) -> Clock:
    if not reference_time_utc:
        return FrozenClock(REFERENCE_NOW)
    from datetime import datetime, timezone

    instant = datetime.fromisoformat(reference_time_utc.replace("Z", "+00:00"))
    return FrozenClock(instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc))
