"""Executable proof of the FASE 80 core invariants.

`--mode core-invariants` prints, in one payload, the resolved workspace roots,
the clock in use, a run manifest and the sealed safety envelope, so the four
contracts can be inspected from the command line on any machine and from any
working directory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .core import FrozenClock, RunManifest, SafetyEnvelope, SystemClock, workspace_paths


def run_core_invariants_report(*, config: Any = None, reference_time_utc: str = "") -> dict[str, Any]:
    paths = workspace_paths()
    clock = _clock(reference_time_utc)
    envelope = SafetyEnvelope.from_config(config) if config is not None else SafetyEnvelope()
    manifest = RunManifest.build(mode="core-invariants", clock=clock, workspace=paths, config=config, envelope=envelope)
    payload = {
        "mode": "core-invariants",
        "workspace": paths.as_dict(),
        "scripts_dir": str(paths.scripts_dir),
        "reports_dir": str(paths.reports_dir),
        "clock_type": type(clock).__name__,
        "clock_now_utc": clock.now_utc().isoformat(),
        "current_operational_day": clock.current_operational_day_iso(),
        "cwd_independent": True,
        "safety": envelope.as_dict(),
        "paper_only": envelope.paper_only,
    }
    return manifest.attach(payload)


def _clock(reference_time_utc: str):
    if not reference_time_utc:
        return SystemClock()
    instant = datetime.fromisoformat(reference_time_utc.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return FrozenClock(instant)
