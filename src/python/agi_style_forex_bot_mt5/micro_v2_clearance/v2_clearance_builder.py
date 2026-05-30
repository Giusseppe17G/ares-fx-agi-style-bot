"""Build a separate V2-only paper risk clearance ledger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .clearance_ledger_adapter import write_json


def build_v2_clearance_ledger(
    *,
    output_dir: str | Path,
    base_clearance_audit: Mapping[str, Any],
    v2_profile_config: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "clearance_id": f"v2prc_{uuid4().hex}",
        "created_at_utc": now,
        "reviewer": "operator",
        "reason": "FASE 51 explicit BALANCED_STABLE_MICRO_V2 paper dry-run clearance",
        "cleared_for_profile": "BALANCED_STABLE_MICRO_V2",
        "canonical_cleared_for_profile": "BALANCED_STABLE_MICRO_V2",
        "cleared_for_profile_canonical": "BALANCED_STABLE_MICRO_V2",
        "clearance_scope": "PAPER_DRY_RUN_ONLY",
        "cleared_for_paper_shadow": True,
        "approved_for_demo": False,
        "approved_for_live": False,
        "not_for_demo_live": True,
        "not_for_live": True,
        "source_phase": "FASE_51_MICRO_V2_PAPER_RISK_CLEARANCE",
        "depends_on_phase_48": True,
        "depends_on_phase_50": True,
        "base_clearance_preserved": True,
        "base_clearance_sha256": base_clearance_audit.get("base_clearance_sha256", ""),
        "v2_profile_config": str(v2_profile_config),
        "latest_halt_utc": "",
        "latest_halt_utc_at_clearance": "",
        "created_after_halt_utc": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    ledger = {
        "mode": "micro-v2-paper-risk-clearance-ledger",
        "clearance_scope": "PAPER_DRY_RUN_ONLY",
        "clearances": [entry],
        "updated_at_utc": now,
        "base_clearance_preserved": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = output / "paper_risk_clearance_v2_ledger.json"
    write_json(path, ledger)
    return {**entry, "ledger_path": str(path), "ledger": ledger}


def ledger_preview(clearance: Mapping[str, Any]) -> str:
    return json.dumps({key: value for key, value in clearance.items() if key != "ledger"}, indent=2, sort_keys=True)
