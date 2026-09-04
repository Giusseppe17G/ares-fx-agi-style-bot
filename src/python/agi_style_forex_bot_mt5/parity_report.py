"""FASE 82 parity report: instrument metadata, execution model and pipeline stages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import FrozenClock, RunManifest, SafetyEnvelope, workspace_paths
from .core.parity import REFERENCE_NOW, build_fixture, compare_pipelines


def run_backtest_live_parity_report(*, output_dir: str | Path | None = None, reference_time_utc: str = "") -> dict[str, Any]:
    paths = workspace_paths()
    clock = _clock(reference_time_utc)
    fixture = build_fixture(clock=clock)
    parity = compare_pipelines(fixture)
    manifest = RunManifest.build(
        mode="backtest-live-parity",
        clock=clock,
        workspace=paths,
        symbols=[fixture.instrument.canonical_symbol],
        timeframe="M5",
        seed=fixture.seed,
    )

    output = Path(output_dir) if output_dir is not None else paths.reports_dir / "backtest_live_parity"
    output.mkdir(parents=True, exist_ok=True)
    created = []
    for name, payload in (("pipeline_parity.json", parity), ("pipeline_stages.json", {"stages": parity["stages"]})):
        target = output / name
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        created.append(str(target))

    summary = {
        "mode": "backtest-live-parity",
        "parity_status": parity["parity_status"],
        "decision_count": parity["decision_count"],
        "equivalent_decision_count": parity["equivalent_decision_count"],
        "decision_parity_pct": parity["decision_parity_pct"],
        "difference_count": parity["difference_count"],
        "stage_count": parity["stage_count"],
        "shared_stage_count": parity["shared_stage_count"],
        "parity_gap_stage_count": parity["parity_gap_stage_count"],
        "parity_gap_stage_ids": parity["parity_gap_stage_ids"],
        "stage_parity_pct": round(parity["shared_stage_count"] / parity["stage_count"] * 100.0, 4),
        "instrument_metadata_source": fixture.instrument.source,
        "reports_created": created,
    }
    return manifest.attach(SafetyEnvelope().seal(summary, full=True))


def _clock(reference_time_utc: str):
    if not reference_time_utc:
        return FrozenClock(REFERENCE_NOW)
    from datetime import datetime, timezone

    instant = datetime.fromisoformat(reference_time_utc.replace("Z", "+00:00"))
    return FrozenClock(instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc))
