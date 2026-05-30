"""Report orchestration for Micro V2 symbol rejection root-cause audit."""

from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .allowed_universe_audit import audit_allowed_universe
from .broker_symbol_mapping_audit import audit_broker_symbol_mapping
from .profile_symbol_guard_audit import audit_profile_symbol_guard
from .stable_gate_symbol_audit import audit_stable_gate_symbols
from .symbol_normalization_audit import audit_symbol_normalization, normalize_symbol
from .symbol_rejection_loader import load_symbol_rejection_inputs, symbol_rejection_events


NEW_LABELS = {"STALE_TICK_REJECTION", "MARKET_CLOSED_REJECTION", "FUTURE_SIGNAL_REJECTION", "INVALID_MARKET_SNAPSHOT_REJECTION"}


def run_micro_v2_symbol_rejection_audit(
    *,
    v2_sqlite: str | Path = "data/sqlite/forward-shadow-v2-dryrun.sqlite3",
    v2_log_dir: str | Path = "data/logs/forward-shadow-v2-dryrun",
    reports_root: str | Path = "data/reports",
    v2_profile_config: str | Path = "data/reports/paper_risk/balanced_stable_micro_v2.ini",
    stable_gate: str | Path = "data/reports/stable_gate/stable_gate_summary.json",
    monitor_dir: str | Path = "data/reports/micro_v2_dry_run_monitor",
    output_dir: str | Path = "data/reports/micro_v2_symbol_rejection_audit",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = load_symbol_rejection_inputs(
        v2_sqlite=v2_sqlite,
        v2_log_dir=v2_log_dir,
        reports_root=reports_root,
        v2_profile_config=v2_profile_config,
        stable_gate=stable_gate,
        monitor_dir=monitor_dir,
    )
    dataset = inputs["dataset"]
    rejections = symbol_rejection_events(dataset)
    new_label_counts = _new_label_counts(dataset)
    rejected_rows = _rejected_symbol_rows(rejections)
    rejected_symbols = [str(row.get("symbol", "")) for row in rejected_rows]
    symbols_seen = _symbols_seen(dataset, rejections)
    normalization = audit_symbol_normalization(rejections)
    universe = audit_allowed_universe(inputs["profile"], symbols_seen, rejected_symbols)
    profile_guard = audit_profile_symbol_guard(inputs["profile"])
    stable_gate_audit = audit_stable_gate_symbols(inputs["stable_gate"], rejected_symbols)
    broker_mapping = audit_broker_symbol_mapping(rejections)
    status, root_cause, action, create_candidate = _classify(normalization, universe, stable_gate_audit, broker_mapping, len(rejections))
    summary = {
        "mode": "micro-v2-symbol-rejection-audit",
        "micro_v2_symbol_rejection_status": status,
        "symbol_rejection_root_cause": root_cause,
        "symbol_rejection_event_count": len(rejections),
        "new_rejection_label_counts": new_label_counts,
        "rejected_symbols_top": rejected_rows[:10],
        "allowed_universe_detected": universe.get("allowed_symbols", []),
        "disabled_symbols_detected": universe.get("disabled_symbols", []),
        "stable_gate_allowed_symbols": stable_gate_audit.get("stable_gate_allowed_symbols", []),
        "stable_gate_disabled_symbols": stable_gate_audit.get("stable_gate_disabled_symbols", []),
        "profile_symbol_guard_status": profile_guard.get("profile_symbol_guard_status", ""),
        "normalization_status": normalization.get("normalization_status", ""),
        "broker_symbol_mapping_status": broker_mapping.get("broker_symbol_mapping_status", ""),
        "fix_candidate_created": create_candidate,
        "recommended_next_action": action,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    paths = _write_reports(output, summary, rejected_rows, normalization, universe, profile_guard, stable_gate_audit, broker_mapping, create_candidate, v2_profile_config)
    return {**summary, "reports_created": [str(path) for path in paths]}


def _classify(
    normalization: Mapping[str, Any],
    universe: Mapping[str, Any],
    stable_gate: Mapping[str, Any],
    broker_mapping: Mapping[str, Any],
    rejection_count: int,
) -> tuple[str, str, str, bool]:
    if rejection_count == 0:
        return "SYMBOL_REJECTION_NOT_ENOUGH_DATA", "NO_SYMBOL_REJECTION_EVENTS_FOUND", "KEEP_COLLECTING_V2_DATA", False
    if int(normalization.get("cli_comma_literal_symbol_count", 0) or 0) > 0:
        return "SYMBOL_REJECTION_DUE_TO_CLI_SYMBOL_PARSE", "CLI_SYMBOLS_ARRIVED_AS_COMMA_LITERAL", "RERUN_V2_WITH_COMMA_SEPARATED_SYMBOLS_CONFIRMED_IN_NEXT_PHASE", False
    if str(universe.get("allowed_symbols_type_status", "")) != "OK":
        return "SYMBOL_REJECTION_DUE_TO_TYPE_MISMATCH", str(universe.get("allowed_symbols_type_status")), "REBUILD_SYMBOL_UNIVERSE_AS_EXPLICIT_CSV_IN_REVIEW_PHASE", True
    if universe.get("profile_universe_status") in {"PROFILE_UNIVERSE_MISMATCH", "PROFILE_DISABLED_SYMBOL_MATCH"}:
        return "SYMBOL_REJECTION_DUE_TO_PROFILE_UNIVERSE", str(universe.get("profile_universe_status")), "REVIEW_NON_ACTIVE_SYMBOL_UNIVERSE_CANDIDATE", True
    if stable_gate.get("stable_gate_symbol_status") in {"STABLE_GATE_UNIVERSE_MISMATCH", "STABLE_GATE_DISABLED_SYMBOL_MATCH"}:
        return "SYMBOL_REJECTION_DUE_TO_STABLE_GATE_UNIVERSE", str(stable_gate.get("stable_gate_symbol_status")), "REVIEW_STABLE_GATE_SYMBOL_SCOPE_OFFLINE", False
    if int(normalization.get("broker_suffix_mismatch_count", 0) or 0) > 0 or broker_mapping.get("broker_symbol_mapping_status") == "BROKER_SUFFIX_MISMATCH":
        return "SYMBOL_REJECTION_DUE_TO_BROKER_SUFFIX", "BROKER_SYMBOL_SUFFIX_DIFFERS_FROM_CANONICAL", "REVIEW_BROKER_SYMBOL_MAPPING_CANDIDATE", True
    if broker_mapping.get("broker_symbol_mapping_status") == "STALE_TICK_REJECTION_MISCLASSIFIED_AS_SYMBOL_REJECTED":
        return "SYMBOL_REJECTION_ROOT_CAUSE_FOUND", "STALE_TICK_OR_MARKET_CLOSED_REJECTION_RECORDED_AS_SYMBOL_REJECTED", "KEEP_COLLECTING_V2_DATA_WHEN_MARKET_TICKS_ARE_FRESH_OR_REVIEW_REJECTION_LABELING_OFFLINE", False
    return "SYMBOL_REJECTION_REQUIRES_MANUAL_REVIEW", "NO_DETERMINISTIC_SYMBOL_UNIVERSE_OR_MAPPING_CAUSE_FOUND", "MANUAL_REVIEW_SYMBOL_REJECTION_EVENTS", False


def _new_label_counts(dataset: Mapping[str, Any]) -> dict[str, int]:
    counts = {label: 0 for label in sorted(NEW_LABELS)}
    for event in dataset.get("events", []):
        event_type = str(event.get("event_type", "")).upper()
        if event_type in counts:
            counts[event_type] += 1
    return counts


def _rejected_symbol_rows(rejections: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    reason_counter: dict[str, Counter[str]] = {}
    for event in rejections:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        symbol = normalize_symbol(event.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "UNKNOWN") or "UNKNOWN"
        reason = str(payload.get("normalization_reason") or payload.get("reject_reason") or payload.get("reason") or event.get("message") or "symbol_rejected")
        counter[symbol] += 1
        reason_counter.setdefault(symbol, Counter())[reason] += 1
    return [
        {
            "symbol": symbol,
            "count": count,
            "top_reason": reason_counter.get(symbol, Counter()).most_common(1)[0][0] if reason_counter.get(symbol) else "",
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
        for symbol, count in counter.most_common()
    ]


def _symbols_seen(dataset: Mapping[str, Any], rejections: list[Mapping[str, Any]]) -> list[str]:
    values: set[str] = set()
    for item in [*dataset.get("events", []), *dataset.get("paper_trades", []), *rejections]:
        payload = item.get("payload", {}) if isinstance(item.get("payload"), Mapping) else {}
        symbol = normalize_symbol(item.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "")
        if symbol:
            values.add(symbol)
    return sorted(values)


def _write_reports(
    output: Path,
    summary: Mapping[str, Any],
    rejected_rows: list[Mapping[str, Any]],
    normalization: Mapping[str, Any],
    universe: Mapping[str, Any],
    profile_guard: Mapping[str, Any],
    stable_gate: Mapping[str, Any],
    broker_mapping: Mapping[str, Any],
    create_candidate: bool,
    profile_config: str | Path,
) -> list[Path]:
    paths = [
        output / "micro_v2_symbol_rejection_summary.json",
        output / "rejected_symbols.csv",
        output / "symbol_normalization_audit.json",
        output / "allowed_universe_audit.json",
        output / "stable_gate_symbol_audit.json",
        output / "broker_symbol_mapping_audit.json",
        output / "symbol_rejection_fix_plan.md",
        output / "recommendations.md",
        output / "report.html",
    ]
    _write_json(paths[0], summary)
    _write_csv(paths[1], rejected_rows)
    _write_json(paths[2], normalization)
    _write_json(paths[3], {**universe, "profile_guard": profile_guard})
    _write_json(paths[4], stable_gate)
    _write_json(paths[5], broker_mapping)
    paths[6].write_text(_fix_plan(summary), encoding="utf-8")
    paths[7].write_text(_recommendations(summary), encoding="utf-8")
    paths[8].write_text(f"<html><body><h1>Micro V2 Symbol Rejection Audit</h1><pre>{html.escape(json.dumps(_jsonable(summary), indent=2, sort_keys=True))}</pre></body></html>", encoding="utf-8")
    if create_candidate:
        candidate = output / "balanced_stable_micro_v2_symbol_fix_candidate.ini"
        candidate.write_text(_candidate_ini(summary, profile_config), encoding="utf-8")
        paths.append(candidate)
    return paths


def _fix_plan(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Symbol Rejection Fix Plan

Status: `{summary.get('micro_v2_symbol_rejection_status')}`

Root cause: `{summary.get('symbol_rejection_root_cause')}`

Recommended next action: `{summary.get('recommended_next_action')}`

This plan is non-active. Do not edit active profiles, stable gate, ledgers, SQLite, or logs from this phase.
"""


def _recommendations(summary: Mapping[str, Any]) -> str:
    return f"""# Micro V2 Symbol Rejection Audit

Rejected symbols top: `{summary.get('rejected_symbols_top')}`

Allowed universe detected: `{summary.get('allowed_universe_detected')}`

Fix candidate created: `{summary.get('fix_candidate_created')}`

This audit is offline/read-only and does not authorize demo/live execution.
"""


def _candidate_ini(summary: Mapping[str, Any], profile_config: str | Path) -> str:
    return "\n".join(
        [
            "PROFILE_NAME=BALANCED_STABLE_MICRO_V2_SYMBOL_FIX_CANDIDATE",
            "SOURCE_PROFILE_CONFIG=" + str(profile_config),
            "NOT_ACTIVE_RESEARCH_ONLY=true",
            "APPROVED_FOR_PAPER_DRY_RUN_ONLY=false",
            "REQUIRES_PHASE_REVIEW=true",
            "PAPER_ONLY=true",
            "NOT_FOR_DEMO_LIVE=true",
            "NOT_FOR_LIVE=true",
            "SOURCE_PHASE=FASE_54_MICRO_V2_SYMBOL_REJECTION_AUDIT",
            "ROOT_CAUSE=" + str(summary.get("symbol_rejection_root_cause", "")),
            "",
        ]
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()} | {"execution_attempted", "order_send_called", "order_check_called"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, False if key in {"execution_attempted", "order_send_called", "order_check_called"} else "") for key in fieldnames})


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
