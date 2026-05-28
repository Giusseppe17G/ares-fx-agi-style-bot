"""Quarantine ledger for historical telemetry timestamp issues."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def load_quarantine_ledger(output_dir: str | Path = "data/reports/telemetry_repair") -> dict[str, Any]:
    path = Path(output_dir) / "telemetry_quarantine_ledger.json"
    if not path.exists():
        return {"mode": "telemetry-quarantine-ledger", "issues": [], "execution_attempted": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"mode": "telemetry-quarantine-ledger", "issues": [], "execution_attempted": False}
    except (OSError, json.JSONDecodeError):
        return {"mode": "telemetry-quarantine-ledger", "issues": [], "execution_attempted": False}


def write_quarantine_ledger(output_dir: str | Path, ledger: Mapping[str, Any]) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "telemetry_quarantine_ledger.json"
    path.write_text(json.dumps(_jsonable(ledger), indent=2, sort_keys=True), encoding="utf-8")
    return path


def quarantine_historical_issues(
    *,
    issues: list[Mapping[str, Any]],
    output_dir: str | Path,
    reason: str,
    status: str = "QUARANTINED",
    issue_class: str = "",
    reviewer: str = "operator",
) -> dict[str, Any]:
    """Mark only historical issues in the ledger; do not mutate source artifacts."""

    ledger = load_quarantine_ledger(output_dir)
    existing = {str(item.get("issue_id")): dict(item) for item in ledger.get("issues", []) if isinstance(item, Mapping)}
    existing_hashes = {str(item.get("raw_value_hash")) for item in existing.values() if item.get("raw_value_hash")}
    updated = 0
    previously_quarantined = 0
    skipped_active = 0
    skipped_unknown = 0
    selected = 0
    now = datetime.now(timezone.utc).isoformat()
    for issue in issues:
        classification = str(issue.get("classification", ""))
        if issue_class and classification != issue_class:
            continue
        selected += 1
        if classification == "ACTIVE_TELEMETRY_INVALID":
            skipped_active += 1
            continue
        if classification == "UNKNOWN_TELEMETRY_REVIEW_REQUIRED":
            skipped_unknown += 1
            continue
        if classification in {"SAFE_IGNORABLE_TEXT", "TELEMETRY_CLEAN"}:
            continue
        issue_id = str(issue.get("issue_id"))
        issue_hash = raw_value_hash(issue.get("raw_value", ""))
        ledger_status = str(issue.get("ledger_status", "")).upper()
        if issue_id in existing or issue_hash in existing_hashes or classification == "QUARANTINED_HISTORICAL" or ledger_status in {"QUARANTINED", "REVIEWED"}:
            previously_quarantined += 1
            continue
        existing[issue_id] = {
            "issue_id": issue_id,
            "status": status.upper(),
            "reviewer": reviewer,
            "reason": reason,
            "timestamp_utc": now,
            "affected_source": issue.get("source", ""),
            "field_name": issue.get("field_name", ""),
            "classification": classification,
            "raw_value_hash": issue_hash,
            "raw_value_redacted_safe": _safe_raw(issue.get("raw_value", "")),
            "execution_attempted": False,
        }
        existing_hashes.add(issue_hash)
        updated += 1
    new_ledger = {
        "mode": "telemetry-quarantine-ledger",
        "updated_at_utc": now,
        "issues": sorted(existing.values(), key=lambda item: str(item.get("issue_id"))),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    path = write_quarantine_ledger(output_dir, new_ledger)
    return {
        "ledger_path": str(path),
        "selected_issues": selected,
        "previously_quarantined_count": previously_quarantined,
        "newly_quarantined_count": updated,
        "quarantined_or_reviewed": previously_quarantined + updated,
        "skipped_active_blocking": skipped_active,
        "skipped_unknown_review": skipped_unknown,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def raw_value_hash(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()


def _safe_raw(value: Any) -> str:
    text = str(value)
    return text[:120]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
