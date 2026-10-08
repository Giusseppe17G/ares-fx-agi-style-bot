"""Legacy-vs-canonical equivalence harness.

No legacy detector is retired on the strength of an argument. Each one that is a
callable function over an events dataset is run side by side with the canonical
detector on the same representative scenarios, and every disagreement is
recorded rather than smoothed over.

Two different questions are being asked across the legacy code, so each detector
is compared against the matching canonical answer:

* EVIDENCE_PRESENT  -- "is there any halt evidence in this dataset?"
                       canonical: halt_event_count > 0
* HALT_ACTIVE_TODAY -- "is a halt in force for the current operational day?"
                       canonical: halt_active

Comparing an EVIDENCE_PRESENT detector against `halt_active` would manufacture
disagreements that do not exist, so the question is part of the record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..clock import Clock, FrozenClock, resolve_clock
from ..safety import SafetyEnvelope
from .halt_detector import detect_halt


EVIDENCE_PRESENT = "EVIDENCE_PRESENT"
HALT_ACTIVE_TODAY = "HALT_ACTIVE_TODAY"

# Legacy rules do not all read the same input. An event-scanning rule and a
# drawdown-threshold rule cannot be compared on the same scenario: running a
# threshold rule against an event-only dataset manufactures a disagreement that
# says nothing about either rule. Each detector declares its dimension and is
# only compared on scenarios that carry the input it reads.
EVENT_SCAN = "EVENT_SCAN"
METRIC_THRESHOLD = "METRIC_THRESHOLD"

REFERENCE_NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class LegacyDetector:
    """One legacy halt rule, wrapped so it can be run on a common dataset."""

    detector_id: str
    module: str
    function: str
    question: str
    dimension: str
    run: Callable[[Mapping[str, Any], Clock], bool]
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    dataset: Mapping[str, Any]
    dimension: str = EVENT_SCAN


def representative_scenarios() -> list[Scenario]:
    """Scenarios covering every behaviour the legacy detectors disagree about."""

    today = REFERENCE_NOW
    yesterday = today - timedelta(days=1)
    long_ago = today - timedelta(days=30)

    def event(**kwargs: Any) -> dict[str, Any]:
        base = {"source": "sqlite:events", "event_type": "", "message": "", "timestamp_utc": "", "payload": {}}
        base.update(kwargs)
        return base

    return [
        Scenario("no_halt", "Only heartbeats and a profitable closed trade.", {
            "events": [
                event(event_type="HEARTBEAT", timestamp_utc=today.isoformat()),
                event(event_type="PAPER_TRADE_CLOSED", timestamp_utc=today.isoformat(), payload={"latest_exit_reason": "TAKE_PROFIT"}),
            ]
        }),
        Scenario("active_halt_today", "A drawdown halt earlier on the current operational day.", {
            "events": [event(event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc=today.replace(hour=10).isoformat(), payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"})]
        }),
        Scenario("historical_halt_only", "A halt from yesterday: the daily reset has happened.", {
            "events": [event(event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc=yesterday.isoformat(), payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"})]
        }),
        Scenario("old_halt_written_last", "An active halt followed in row order by an older halt.", {
            "events": [
                event(event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc=today.replace(hour=9).isoformat(), payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"}),
                event(source="jsonl:events.jsonl:1", event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc=long_ago.isoformat(), payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"}),
            ]
        }),
        Scenario("shadow_halted_wrapper", "PAPER_SHADOW_HALTED carrying the real cause in the payload.", {
            "events": [event(event_type="PAPER_SHADOW_HALTED", timestamp_utc=today.replace(hour=11).isoformat(), payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"})]
        }),
        Scenario("halt_in_payload_error", "The halt token only appears in payload.error.", {
            "events": [event(event_type="FORWARD_SHADOW_CRITICAL_ERROR", timestamp_utc=today.replace(hour=12).isoformat(), payload={"error": "PAPER_DAILY_DRAWDOWN_HALT tripped"})]
        }),
        Scenario("lowercase_token", "The halt token is written in lower case.", {
            "events": [event(event_type="paper_daily_drawdown_halt", timestamp_utc=today.replace(hour=13).isoformat(), payload={"halt_reason": "paper_daily_drawdown_halt"})]
        }),
        Scenario("malformed_timestamp", "Halt evidence with an unparseable timestamp.", {
            "events": [event(event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc="not-a-timestamp", payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"})]
        }),
        Scenario("mixed_sources_with_later_activity", "SQLite halt, then a later JSONL heartbeat and a later closed trade.", {
            "events": [
                event(event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc=today.replace(hour=8).isoformat(), payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"}),
                event(source="jsonl:events.jsonl:5", event_type="HEARTBEAT", timestamp_utc=today.replace(hour=15).isoformat()),
                event(source="jsonl:events.jsonl:6", event_type="PAPER_TRADE_CLOSED", timestamp_utc=today.replace(hour=16).isoformat(), payload={"latest_exit_reason": "STOP_LOSS"}),
            ]
        }),
        Scenario("config_error_halt", "CONFIG_ERROR / PAPER_STATE_ERROR rather than a drawdown halt.", {
            "events": [event(event_type="FORWARD_SHADOW_CRITICAL_ERROR", timestamp_utc=today.replace(hour=14).isoformat(), payload={"halt_reason": "PAPER_STATE_ERROR", "error": "CONFIG_ERROR"})]
        }),
        Scenario("stale_halt", "A halt 30 days old.", {
            "events": [event(event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc=long_ago.isoformat(), payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"})]
        }),
        Scenario("metrics_drawdown_breached", "Daily drawdown well past the -3.0 limit.", {
            "events": [],
            "metrics": {"daily_drawdown_shadow": -9.996, "drawdown_paper": -9.996, "timestamp_utc": today.isoformat()},
        }, dimension=METRIC_THRESHOLD),
        Scenario("metrics_drawdown_at_limit", "Daily drawdown exactly at the -3.0 limit.", {
            "events": [],
            "metrics": {"daily_drawdown_shadow": -3.0, "drawdown_paper": -3.0, "timestamp_utc": today.isoformat()},
        }, dimension=METRIC_THRESHOLD),
        Scenario("metrics_drawdown_within_limit", "Daily drawdown inside the limit.", {
            "events": [],
            "metrics": {"daily_drawdown_shadow": -0.5, "drawdown_paper": -0.5, "timestamp_utc": today.isoformat()},
        }, dimension=METRIC_THRESHOLD),
    ]


def legacy_detectors() -> list[LegacyDetector]:
    """The legacy halt rules that are callable as functions over a dataset."""

    from agi_style_forex_bot_mt5.micro_v2_closed_loss_scope_decision.daily_drawdown_legitimacy_audit import _halt_count
    from agi_style_forex_bot_mt5.micro_v2_daily_drawdown_state_recovery.drawdown_halt_loader import drawdown_halt_events
    from agi_style_forex_bot_mt5.micro_v2_daily_reset_readiness.daily_halt_status_audit import audit_daily_halt_status
    from agi_style_forex_bot_mt5.micro_v2_sqlite_halt_forensics.halt_event_scanner import current_is_halt_event_match
    from agi_style_forex_bot_mt5.paper_trading.paper_state import _halt_reason

    def _events(dataset: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        return [event for event in dataset.get("events", []) if isinstance(event, Mapping)]

    return [
        LegacyDetector(
            "daily_reset_readiness.audit_daily_halt_status",
            "micro_v2_daily_reset_readiness/daily_halt_status_audit.py",
            "audit_daily_halt_status",
            HALT_ACTIVE_TODAY,
            EVENT_SCAN,
            lambda dataset, clock: bool(audit_daily_halt_status(dataset, current_utc=clock.now_utc()).get("daily_halt_active")),
            note="Repaired in FASE 79: timestamp ordering plus top-level fields.",
        ),
        LegacyDetector(
            "daily_drawdown_state_recovery.drawdown_halt_events",
            "micro_v2_daily_drawdown_state_recovery/drawdown_halt_loader.py",
            "drawdown_halt_events",
            EVIDENCE_PRESENT,
            EVENT_SCAN,
            lambda dataset, clock: bool(drawdown_halt_events(dict(dataset))),
            note="Case-sensitive; scans payload.error; no ordering.",
        ),
        LegacyDetector(
            "closed_loss_scope_decision._halt_count",
            "micro_v2_closed_loss_scope_decision/daily_drawdown_legitimacy_audit.py",
            "_halt_count",
            EVIDENCE_PRESENT,
            EVENT_SCAN,
            lambda dataset, clock: _halt_count(dataset) > 0,
            note="Same rule as the recovery loader, counting only.",
        ),
        LegacyDetector(
            "sqlite_halt_forensics.current_is_halt_event_match",
            "micro_v2_sqlite_halt_forensics/halt_event_scanner.py",
            "current_is_halt_event_match",
            EVIDENCE_PRESENT,
            EVENT_SCAN,
            lambda dataset, clock: any(current_is_halt_event_match(event) for event in _events(dataset)),
            note="Models the pre-FASE-79 reset detector for forensics comparison.",
        ),
        LegacyDetector(
            "paper_trading.paper_state._halt_reason",
            "paper_trading/paper_state.py",
            "_halt_reason",
            EVIDENCE_PRESENT,
            METRIC_THRESHOLD,
            lambda dataset, clock: _halt_reason(_metrics_of(dataset), _state_of(dataset)) == "PAPER_DAILY_DRAWDOWN_HALT",
            note="Threshold rule on daily_drawdown_shadow <= -3.0, not an event scan.",
        ),
        LegacyDetector(
            "observability.operational_status.threshold",
            "observability/operational_status.py",
            "daily_drawdown_status",
            EVIDENCE_PRESENT,
            METRIC_THRESHOLD,
            lambda dataset, clock: float(_metrics_of(dataset).get("drawdown_paper", 0.0) or 0.0) <= -3.0,
            note="One of four hardcoded <= -3.0 threshold copies.",
        ),
        LegacyDetector(
            "forward_evidence.forward_metrics.threshold",
            "forward_evidence/forward_metrics.py",
            "paper_drawdown_status",
            EVIDENCE_PRESENT,
            METRIC_THRESHOLD,
            lambda dataset, clock: float(_metrics_of(dataset).get("daily_drawdown_shadow", 0.0) or 0.0) <= -3.0,
            note="Second hardcoded <= -3.0 threshold copy.",
        ),
    ]


def compare_detectors(*, clock: Clock | None = None) -> list[dict[str, Any]]:
    """Run every legacy detector and the canonical one on every scenario."""

    resolved = resolve_clock(clock) if clock is not None else FrozenClock(REFERENCE_NOW)
    rows: list[dict[str, Any]] = []
    for detector in legacy_detectors():
        for scenario in representative_scenarios():
            if scenario.dimension != detector.dimension:
                continue
            assessment = detect_halt(scenario.dataset, metrics=_metrics_of(scenario.dataset) or None, clock=resolved)
            canonical = assessment.halt_active if detector.question == HALT_ACTIVE_TODAY else assessment.halt_event_count > 0
            try:
                legacy = bool(detector.run(scenario.dataset, resolved))
                legacy_error = ""
            except Exception as error:  # a legacy rule that cannot run on this shape is itself a finding
                legacy = False
                legacy_error = f"{type(error).__name__}: {error}"
            rows.append(
                {
                    "detector_id": detector.detector_id,
                    "module": detector.module,
                    "function": detector.function,
                    "question": detector.question,
                    "dimension": detector.dimension,
                    "note": detector.note,
                    "scenario_id": scenario.scenario_id,
                    "scenario": scenario.description,
                    "old_status": "HALT" if legacy else "NO_HALT",
                    "new_status": "HALT" if canonical else "NO_HALT",
                    "same_decision": legacy == canonical,
                    "legacy_error": legacy_error,
                    "different_fields": [] if legacy == canonical else ["halt_active" if detector.question == HALT_ACTIVE_TODAY else "halt_event_count"],
                    "canonical_halt_kind": assessment.halt_kind.value,
                    "canonical_halt_age": assessment.halt_age.value,
                }
            )
    return rows


def diff_verdicts() -> dict[str, str]:
    """Adjudicated explanation for every known disagreement.

    Each entry states which side is correct and why. A disagreement without an
    entry here is reported as UNEXPLAINED and fails the equivalence gate.
    """

    return {
        # --- legacy rules that miss real halt evidence -------------------------------
        "daily_drawdown_state_recovery.drawdown_halt_events|lowercase_token": "LEGACY_BEHAVIOR_BUG: the legacy rule is case-sensitive, so a lower-case halt token is not detected. The canonical detector is case-insensitive.",
        "closed_loss_scope_decision._halt_count|lowercase_token": "LEGACY_BEHAVIOR_BUG: same case-sensitive rule as the recovery loader.",
        "sqlite_halt_forensics.current_is_halt_event_match|lowercase_token": "LEGACY_BEHAVIOR_BUG: the pre-FASE-79 detector is case-sensitive.",
        "sqlite_halt_forensics.current_is_halt_event_match|halt_in_payload_error": "LEGACY_BEHAVIOR_BUG: the pre-FASE-79 detector never read payload.error, so a halt reported only there was invisible to it.",
        "sqlite_halt_forensics.current_is_halt_event_match|config_error_halt": "LEGACY_BEHAVIOR_BUG: the pre-FASE-79 detector only matched PAPER_DAILY_DRAWDOWN, so a PAPER_STATE_ERROR/CONFIG_ERROR halt was not halt evidence at all.",
        "daily_reset_readiness.audit_daily_halt_status|halt_in_payload_error": "LEGACY_BEHAVIOR_BUG: the FASE 79 detector reads halt_reason/alert_code/paused_reason but not payload.error, which the two recovery loaders do read. A halt reported only in payload.error was therefore invisible to reset readiness while being visible to the recovery audit. The canonical detector is the union of both field sets.",

        # --- deliberate canonical changes, each safer than the legacy behaviour -------
        "daily_reset_readiness.audit_daily_halt_status|malformed_timestamp": "CANONICAL_FAIL_CLOSED: the legacy detector discards halt evidence whose timestamp will not parse, and then reports no halt at all, which would permit a relaunch on the strength of unreadable evidence. The canonical detector treats an undatable halt as active and marks evidence_quality=EVIDENCE_MALFORMED. Changing the verdict in the blocking direction is intentional.",
        "daily_reset_readiness.audit_daily_halt_status|config_error_halt": "CANONICAL_WIDER_SCOPE: the legacy detector recognises only drawdown tokens, so a PAPER_STATE_ERROR/CONFIG_ERROR halt is not a halt to it. The legacy relaunch gate still blocked on that state through a separate path (v2_relaunch_gate._paper_state_block), so the gate verdict is unchanged; the canonical detector simply reports the halt where the legacy stack reported it elsewhere.",
        "daily_drawdown_state_recovery.drawdown_halt_events|config_error_halt": "CANONICAL_WIDER_SCOPE: the recovery loader scans for drawdown tokens only, by design (it feeds a drawdown recovery report). The canonical detector covers every halt kind and reports the kind explicitly, so a consumer that only wants drawdown halts filters on halt_kind.",
        "closed_loss_scope_decision._halt_count|config_error_halt": "CANONICAL_WIDER_SCOPE: same drawdown-only scope as the recovery loader.",
    }


def build_equivalence_report(*, clock: Clock | None = None) -> dict[str, Any]:
    rows = compare_detectors(clock=clock)
    verdicts = diff_verdicts()
    differences = [row for row in rows if not row["same_decision"]]
    for row in differences:
        key = f"{row['detector_id']}|{row['scenario_id']}"
        row["verdict"] = verdicts.get(key, "UNEXPLAINED")
    unexplained = [row for row in differences if row["verdict"] == "UNEXPLAINED"]
    intentional = [row for row in differences if str(row["verdict"]).startswith("CANONICAL_")]
    detectors = legacy_detectors()
    payload = {
        "mode": "unified-operational-state-equivalence",
        "equivalence_status": "EQUIVALENCE_OK" if not unexplained else "EQUIVALENCE_UNEXPLAINED_DIFFERENCE",
        "legacy_detector_count": len(detectors),
        "scenario_count": len(representative_scenarios()),
        "comparison_count": len(rows),
        "same_decision_count": sum(1 for row in rows if row["same_decision"]),
        "difference_count": len(differences),
        "unexplained_difference_count": len(unexplained),
        "legacy_behavior_bug_count": sum(1 for row in differences if str(row["verdict"]).startswith("LEGACY_BEHAVIOR_BUG")),
        "intentional_canonical_change_count": len(intentional),
        "comparisons": rows,
        "differences": differences,
    }
    return SafetyEnvelope().seal(payload)


def write_equivalence_report(output_dir: str | Path, *, clock: Clock | None = None) -> dict[str, Any]:
    report = build_equivalence_report(clock=clock)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "halt_migration_diff.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return {**report, "reports_created": [str(output / "halt_migration_diff.json")]}


def _metrics_of(dataset: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = dataset.get("metrics")
    return metrics if isinstance(metrics, Mapping) else {}


def _state_of(dataset: Mapping[str, Any]) -> Mapping[str, Any]:
    state = dataset.get("operational_state")
    return state if isinstance(state, Mapping) else {}


# --------------------------------------------------------------------------- relaunch gates


@dataclass(frozen=True)
class GateScenario:
    scenario_id: str
    description: str
    dataset: Mapping[str, Any]
    ledger_audit: Mapping[str, Any]
    safety_blocked: bool = False


def gate_scenarios() -> list[GateScenario]:
    today = REFERENCE_NOW
    scope_ok = {"daily_risk_scope_status": "DAILY_RISK_SCOPE_OK_FOR_V2", "latest_v2_ledger_created_at_utc": (today - timedelta(days=1)).isoformat()}
    scope_bad = {"daily_risk_scope_status": "DAILY_RISK_SCOPE_MISSING_V2", "latest_v2_ledger_created_at_utc": ""}
    halt_today = {"source": "sqlite:events", "event_type": "PAPER_DAILY_DRAWDOWN_HALT", "timestamp_utc": today.replace(hour=9).isoformat(), "message": "", "payload": {"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"}}
    halt_yesterday = {**halt_today, "timestamp_utc": (today - timedelta(days=1)).isoformat()}
    valid_open = {"paper_trade_id": "open1", "status": "OPEN", "entry_price": 1.1, "sl_price": 1.09, "tp_price": 1.12}
    invalid_open = {"paper_trade_id": "bad1", "status": "OPEN", "entry_price": 1.1, "sl_price": 1.1, "tp_price": 1.2}

    return [
        GateScenario("clean_after_reset", "Halt expired yesterday, scope OK, no open trades.", {"events": [halt_yesterday], "paper_trades": []}, scope_ok),
        GateScenario("halt_active_today", "Halt active for the current operational day.", {"events": [halt_today], "paper_trades": []}, scope_ok),
        GateScenario("scope_invalid", "Halt expired but the daily risk scope is not valid for V2.", {"events": [halt_yesterday], "paper_trades": []}, scope_bad),
        GateScenario("open_trade_blocks", "A valid open paper trade is still running.", {"events": [halt_yesterday], "paper_trades": [valid_open]}, scope_ok),
        GateScenario("invalid_trade_blocks", "An open paper trade has an invalid risk distance.", {"events": [halt_yesterday], "paper_trades": [invalid_open]}, scope_ok),
        GateScenario("safety_flag_blocks", "A source report claims execution was attempted.", {"events": [halt_yesterday], "paper_trades": []}, scope_ok, safety_blocked=True),
        GateScenario("old_halt_written_last", "An active halt followed in row order by a much older halt.", {"events": [halt_today, {**halt_yesterday, "source": "jsonl:events.jsonl:1", "timestamp_utc": (today - timedelta(days=30)).isoformat()}], "paper_trades": []}, scope_ok),
    ]


def compare_relaunch_gates(*, clock: Clock | None = None) -> list[dict[str, Any]]:
    """Run every legacy relaunch gate and the canonical one on the same scenarios."""

    from agi_style_forex_bot_mt5.micro_v2_daily_reset_readiness.daily_halt_status_audit import audit_daily_halt_status
    from agi_style_forex_bot_mt5.micro_v2_daily_reset_readiness.v2_relaunch_gate import evaluate_v2_relaunch_gate
    from agi_style_forex_bot_mt5.micro_v2_post_reset_relaunch_pack.daily_reset_recheck import recheck_daily_reset
    from agi_style_forex_bot_mt5.micro_v2_pre_relaunch_safety_pack.reset_relaunch_gate import evaluate_reset_relaunch_gate
    from agi_style_forex_bot_mt5.micro_v2_reset_watcher.reset_gate_recheck import recheck_reset_gate

    from .paper_state import build_paper_state
    from .relaunch_gate import evaluate_relaunch

    resolved = resolve_clock(clock) if clock is not None else FrozenClock(REFERENCE_NOW)
    rows: list[dict[str, Any]] = []

    for scenario in gate_scenarios():
        halt_audit = audit_daily_halt_status(scenario.dataset, current_utc=resolved.now_utc())
        legacy_primary = evaluate_v2_relaunch_gate(
            scenario.dataset,
            safety_blocked=scenario.safety_blocked,
            halt_audit=halt_audit,
            ledger_audit=scenario.ledger_audit,
        )
        # The derived gates consume the primary gate's summary, which is exactly how
        # they are wired in production.
        reset_summary = {
            **legacy_primary,
            "daily_halt_active": halt_audit.get("daily_halt_active", False),
            "daily_reset_occurred": halt_audit.get("daily_reset_occurred", False),
            "daily_risk_scope_status": scenario.ledger_audit.get("daily_risk_scope_status", ""),
        }
        legacy_pre = evaluate_reset_relaunch_gate(reset_summary)
        legacy_pack = recheck_daily_reset(reset_summary)
        legacy_watcher = recheck_reset_gate(
            {
                "post_reset_relaunch": {
                    "post_reset_relaunch_allowed": bool(reset_summary.get("relaunch_allowed", False)),
                    "daily_halt_active": bool(reset_summary.get("daily_halt_active", False)),
                    "daily_reset_occurred": bool(reset_summary.get("daily_reset_occurred", False)),
                    "daily_risk_scope_status": reset_summary.get("daily_risk_scope_status", ""),
                    "daily_risk_scope_verified": reset_summary.get("daily_risk_scope_status") == "DAILY_RISK_SCOPE_OK_FOR_V2",
                    "zero_risk_guard_verified": True,
                    "paper_state_clean_for_relaunch": bool(reset_summary.get("paper_state_clean_for_relaunch", False)),
                    "execution_attempted": scenario.safety_blocked,
                },
                "pre_relaunch_safety": {"zero_risk_guard_enabled": True},
                "daily_risk_scope_repair": {"daily_risk_scope_status_after": reset_summary.get("daily_risk_scope_status", "")},
            }
        )

        paper_state = build_paper_state(scenario.dataset, clock=resolved)
        canonical = evaluate_relaunch(
            paper_state=paper_state,
            safety_blocked=scenario.safety_blocked,
            daily_risk_scope_status=str(scenario.ledger_audit.get("daily_risk_scope_status", "")),
            clock=resolved,
        )

        for gate_id, module, legacy_allowed in (
            ("micro_v2_daily_reset_readiness.evaluate_v2_relaunch_gate", "micro_v2_daily_reset_readiness/v2_relaunch_gate.py", bool(legacy_primary.get("relaunch_allowed", False))),
            ("micro_v2_pre_relaunch_safety_pack.evaluate_reset_relaunch_gate", "micro_v2_pre_relaunch_safety_pack/reset_relaunch_gate.py", bool(legacy_pre.get("relaunch_allowed", False))),
            ("micro_v2_post_reset_relaunch_pack.recheck_daily_reset", "micro_v2_post_reset_relaunch_pack/daily_reset_recheck.py", bool(legacy_pack.get("relaunch_allowed", False))),
            ("micro_v2_reset_watcher.recheck_reset_gate", "micro_v2_reset_watcher/reset_gate_recheck.py", legacy_watcher.get("reset_gate_recheck_status") == "MICRO_V2_RESET_WATCHER_READY_FOR_MANUAL_RELAUNCH"),
        ):
            rows.append(
                {
                    "gate_id": gate_id,
                    "module": module,
                    "scenario_id": scenario.scenario_id,
                    "scenario": scenario.description,
                    "old_allowed": legacy_allowed,
                    "new_allowed": canonical.relaunch_allowed,
                    "same_decision": legacy_allowed == canonical.relaunch_allowed,
                    "canonical_decision": canonical.decision.value,
                    "canonical_blocking_gate_ids": canonical.blocking_gate_ids,
                    "legacy_status": str(legacy_primary.get("v2_relaunch_gate_status", "")),
                }
            )
    return rows


def build_gate_equivalence_report(*, clock: Clock | None = None) -> dict[str, Any]:
    rows = compare_relaunch_gates(clock=clock)
    differences = [row for row in rows if not row["same_decision"]]
    payload = {
        "mode": "unified-relaunch-gate-equivalence",
        "gate_equivalence_status": "GATE_EQUIVALENCE_OK" if not differences else "GATE_EQUIVALENCE_DIFFERENCE",
        "legacy_gate_count": 4,
        "derived_gate_note": "micro_v2_post_reset_relaunch_pack.post_reset_relaunch_report and micro_v2_post_reset_relaunch.relaunch_decision are composite reports built on top of these four, so they are covered transitively rather than compared directly.",
        "scenario_count": len(gate_scenarios()),
        "comparison_count": len(rows),
        "same_decision_count": sum(1 for row in rows if row["same_decision"]),
        "difference_count": len(differences),
        "comparisons": rows,
        "differences": differences,
    }
    return SafetyEnvelope().seal(payload)
