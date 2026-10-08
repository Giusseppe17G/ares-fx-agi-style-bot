"""FASE 81 - unified halt / gate / paper state core.

Covers the canonical detector, paper state, relaunch gate and error hierarchy,
plus the equivalence evidence that justifies retiring the legacy rules.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agi_style_forex_bot_mt5.config import load_config
from agi_style_forex_bot_mt5.core import FrozenClock, assert_safety_flags, workspace_paths
from agi_style_forex_bot_mt5.core.operational_state import (
    DEFAULT_DAILY_DRAWDOWN_LIMIT,
    ConfigurationError,
    DataError,
    EvidenceError,
    EvidenceQuality,
    ExecutionSimulationError,
    HaltAge,
    HaltKind,
    InstrumentError,
    OperationalError,
    PaperStateError,
    PaperStateStatus,
    RelaunchDecision,
    RiskError,
    TimestampError,
    build_paper_state,
    classify_halt_reason,
    detect_halt,
    error_record,
    evaluate_relaunch,
    halt_kind_of,
    is_halt_event,
)
from agi_style_forex_bot_mt5.core.operational_state.equivalence import (
    REFERENCE_NOW,
    build_equivalence_report,
    build_gate_equivalence_report,
)
from agi_style_forex_bot_mt5.micro_v2_daily_reset_readiness.daily_halt_status_audit import audit_daily_halt_status
from agi_style_forex_bot_mt5.unified_operational_state_report import run_unified_operational_state_report

NOW = REFERENCE_NOW
CLOCK = FrozenClock(NOW)


def _event(**kwargs) -> dict:
    base = {"source": "sqlite:events", "event_type": "", "message": "", "timestamp_utc": "", "payload": {}}
    base.update(kwargs)
    return base


def _halt_event(timestamp: datetime, *, reason: str = "PAPER_DAILY_DRAWDOWN_HALT", source: str = "sqlite:events") -> dict:
    return _event(source=source, event_type=reason, timestamp_utc=timestamp.isoformat(), payload={"halt_reason": reason})


# --------------------------------------------------------------------------- halt precedence and ordering


def test_latest_halt_is_chosen_by_timestamp_not_row_order() -> None:
    """FASE J regression: an older halt written last must not mask the active one."""

    dataset = {
        "events": [
            _halt_event(NOW.replace(hour=9)),
            _halt_event(NOW - timedelta(days=30), source="jsonl:events.jsonl:1"),
        ]
    }
    assessment = detect_halt(dataset, clock=CLOCK)
    assert assessment.halt_timestamp_utc == NOW.replace(hour=9).isoformat()
    assert assessment.halt_active is True
    assert assessment.halt_age is HaltAge.ACTIVE
    assert assessment.daily_reset_occurred is False


def test_full_lifecycle_scenario_with_mixed_sources() -> None:
    """FASE J: old halt, current halt, later heartbeat and later closed trade, mixed sources."""

    dataset = {
        "events": [
            _halt_event(NOW - timedelta(days=3), source="sqlite:events"),
            _event(source="jsonl:events.jsonl:1", event_type="HEARTBEAT", timestamp_utc=NOW.replace(hour=15).isoformat()),
            _halt_event(NOW.replace(hour=10), source="jsonl:events.jsonl:2"),
            _event(source="sqlite:events", event_type="PAPER_TRADE_CLOSED", timestamp_utc=NOW.replace(hour=16).isoformat(), payload={"latest_exit_reason": "TAKE_PROFIT"}),
        ]
    }
    assessment = detect_halt(dataset, clock=CLOCK)
    assert assessment.halt_active is True
    assert assessment.halt_timestamp_utc == NOW.replace(hour=10).isoformat()
    assert assessment.halt_source == "jsonl:events.jsonl:2"
    assert assessment.halt_event_count == 2  # the heartbeat and the take-profit close are not halts


def test_higher_precedence_kind_wins_a_timestamp_tie() -> None:
    same_moment = NOW.replace(hour=12)
    dataset = {
        "events": [
            _halt_event(same_moment, reason="PAPER_DAILY_DRAWDOWN_HALT"),
            _event(event_type="FORWARD_SHADOW_CRITICAL_ERROR", timestamp_utc=same_moment.isoformat(), payload={"halt_reason": "PAPER_STATE_ERROR"}),
        ]
    }
    assert detect_halt(dataset, clock=CLOCK).halt_kind is HaltKind.PAPER_STATE


def test_historical_stale_and_active_ages() -> None:
    active = detect_halt({"events": [_halt_event(NOW.replace(hour=1))]}, clock=CLOCK)
    historical = detect_halt({"events": [_halt_event(NOW - timedelta(days=1))]}, clock=CLOCK)
    stale = detect_halt({"events": [_halt_event(NOW - timedelta(days=30))]}, clock=CLOCK)

    assert (active.halt_age, active.halt_active, active.daily_reset_occurred) == (HaltAge.ACTIVE, True, False)
    assert (historical.halt_age, historical.halt_active, historical.daily_reset_occurred) == (HaltAge.HISTORICAL, False, True)
    assert (stale.halt_age, stale.halt_active, stale.daily_reset_occurred) == (HaltAge.STALE, False, True)


def test_no_halt_evidence_reports_none() -> None:
    dataset = {"events": [_event(event_type="HEARTBEAT", timestamp_utc=NOW.isoformat())]}
    assessment = detect_halt(dataset, clock=CLOCK)
    assert assessment.halt_active is False
    assert assessment.halt_kind is HaltKind.NONE
    assert assessment.evidence_quality is EvidenceQuality.EMPTY


# --------------------------------------------------------------------------- evidence quality


def test_malformed_evidence_fails_closed() -> None:
    """Halt evidence with no usable timestamp must never read as 'no halt'."""

    dataset = {"events": [_event(event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc="not-a-timestamp", payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"})]}
    assessment = detect_halt(dataset, clock=CLOCK)
    assert assessment.halt_active is True
    assert assessment.halt_age is HaltAge.MALFORMED
    assert assessment.evidence_quality is EvidenceQuality.MALFORMED
    assert assessment.daily_reset_occurred is False


def test_partial_evidence_keeps_the_datable_verdict() -> None:
    dataset = {
        "events": [
            _halt_event(NOW - timedelta(days=1)),
            _event(event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc="", payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"}),
        ]
    }
    assessment = detect_halt(dataset, clock=CLOCK)
    assert assessment.evidence_quality is EvidenceQuality.PARTIAL
    assert assessment.malformed_event_count == 1
    assert assessment.halt_active is False


# --------------------------------------------------------------------------- field and token coverage


@pytest.mark.parametrize(
    "event,expected",
    [
        (_event(event_type="PAPER_DAILY_DRAWDOWN_HALT"), HaltKind.DAILY_DRAWDOWN),
        (_event(event_type="paper_daily_drawdown_halt"), HaltKind.DAILY_DRAWDOWN),
        (_event(payload={"error": "PAPER_DAILY_DRAWDOWN_HALT tripped"}), HaltKind.DAILY_DRAWDOWN),
        (_event(halt_reason="PAPER_STATE_ERROR"), HaltKind.PAPER_STATE),
        (_event(payload={"halt_reason": "CONFIG_ERROR"}), HaltKind.CONFIG),
        (_event(paused_reason="SHADOW_MANUALLY_PAUSED"), HaltKind.MANUAL),
        (_event(shadow_paused=True), HaltKind.MANUAL),
        (_event(alert_code="PAPER_DAILY_DRAWDOWN"), HaltKind.DAILY_DRAWDOWN),
        (_event(event_type="HEARTBEAT"), HaltKind.NONE),
        (_event(payload={"latest_exit_reason": "TAKE_PROFIT"}), HaltKind.NONE),
    ],
)
def test_canonical_field_and_token_coverage(event: dict, expected: HaltKind) -> None:
    assert halt_kind_of(event) is expected
    assert is_halt_event(event) is (expected is not HaltKind.NONE)


def test_shadow_halted_wrapper_resolves_to_the_real_cause() -> None:
    event = _event(event_type="PAPER_SHADOW_HALTED", timestamp_utc=NOW.isoformat(), payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"})
    assert halt_kind_of(event) is HaltKind.DAILY_DRAWDOWN
    bare = _event(event_type="PAPER_SHADOW_HALTED", timestamp_utc=NOW.isoformat())
    assert halt_kind_of(bare) is HaltKind.UNKNOWN


def test_classify_halt_reason_maps_every_token() -> None:
    assert classify_halt_reason("PAPER_DAILY_DRAWDOWN") is HaltKind.DAILY_DRAWDOWN
    assert classify_halt_reason("PAPER_STATE_ERROR") is HaltKind.PAPER_STATE
    assert classify_halt_reason("CONFIG_ERROR") is HaltKind.CONFIG
    assert classify_halt_reason("") is HaltKind.NONE


# --------------------------------------------------------------------------- SQLite + JSONL merge


def test_sqlite_and_jsonl_records_are_merged_into_one_verdict() -> None:
    dataset = {
        "events": [_halt_event(NOW - timedelta(days=2), source="sqlite:events")],
        "alerts": [{"source": "sqlite:alerts", "alert_code": "PAPER_DAILY_DRAWDOWN", "timestamp_utc": NOW.replace(hour=7).isoformat()}],
        "operational_state": [{"source": "sqlite:operational_state", "halt_reason": "PAPER_DAILY_DRAWDOWN_HALT", "updated_at_utc": NOW.replace(hour=6).isoformat()}],
    }
    assessment = detect_halt(dataset, clock=CLOCK)
    assert assessment.halt_event_count == 3
    assert assessment.halt_source == "sqlite:alerts"
    assert assessment.halt_active is True


def test_metric_threshold_produces_a_halt_record() -> None:
    assessment = detect_halt({"events": []}, metrics={"daily_drawdown_shadow": -9.996, "timestamp_utc": NOW.isoformat()}, clock=CLOCK)
    assert assessment.halt_active is True
    assert assessment.halt_kind is HaltKind.DAILY_DRAWDOWN
    within = detect_halt({"events": []}, metrics={"daily_drawdown_shadow": -0.5, "timestamp_utc": NOW.isoformat()}, clock=CLOCK)
    assert within.halt_active is False
    at_limit = detect_halt({"events": []}, metrics={"daily_drawdown_shadow": DEFAULT_DAILY_DRAWDOWN_LIMIT, "timestamp_utc": NOW.isoformat()}, clock=CLOCK)
    assert at_limit.halt_active is True


# --------------------------------------------------------------------------- paper state


def test_paper_state_classifies_trades_and_cleanliness() -> None:
    dataset = {
        "events": [],
        "paper_trades": [
            {"paper_trade_id": "ok", "status": "OPEN", "entry_price": 1.1, "sl_price": 1.09, "tp_price": 1.12},
            {"paper_trade_id": "bad", "status": "OPEN", "entry_price": 1.1, "sl_price": 1.1, "tp_price": 1.2},
            {"paper_trade_id": "q", "status": "QUARANTINED_INVALID_PAPER_TRADE"},
            {"paper_trade_id": "c", "status": "CLOSED", "pnl": -1.5},
        ],
    }
    state = build_paper_state(dataset, clock=CLOCK)
    assert len(state.open_trades) == 2
    assert len(state.invalid_open_trades) == 1
    assert len(state.quarantined_trades) == 1
    assert len(state.closed_trades) == 1
    assert state.closed_pnl == pytest.approx(-1.5)
    assert state.status is PaperStateStatus.INVALID_OPEN_TRADES
    assert state.clean_for_relaunch is False
    assert_safety_flags(state.as_dict(), context="paper state")


def test_clean_paper_state_is_relaunchable() -> None:
    state = build_paper_state({"events": [], "paper_trades": []}, clock=CLOCK)
    assert state.status is PaperStateStatus.OK
    assert state.clean_for_relaunch is True
    assert state.block_new_entries is False


def test_paper_state_error_and_config_error_take_precedence() -> None:
    config_error = build_paper_state({"events": [], "paper_trades": []}, operational_state={"latest_exit_reason": "CONFIG_ERROR"}, clock=CLOCK)
    assert config_error.status is PaperStateStatus.CONFIG_ERROR
    assert config_error.config_error_active is True

    state_error = build_paper_state({"events": [], "paper_trades": []}, operational_state={"halt_reason": "PAPER_STATE_ERROR"}, clock=CLOCK)
    assert state_error.status is PaperStateStatus.STATE_ERROR
    assert state_error.clean_for_relaunch is False


def test_active_halt_blocks_new_entries() -> None:
    state = build_paper_state({"events": [_halt_event(NOW.replace(hour=8))], "paper_trades": []}, clock=CLOCK)
    assert state.halt.halt_active is True
    assert state.block_new_entries is True


# --------------------------------------------------------------------------- relaunch gate


def test_relaunch_allowed_only_when_everything_is_clean() -> None:
    state = build_paper_state({"events": [_halt_event(NOW - timedelta(days=1))], "paper_trades": []}, clock=CLOCK)
    result = evaluate_relaunch(paper_state=state, daily_risk_scope_status="DAILY_RISK_SCOPE_OK_FOR_V2", clock=CLOCK)
    assert result.relaunch_allowed is True
    assert result.decision is RelaunchDecision.ALLOWED
    assert result.blocking_gates == ()
    assert_safety_flags(result.as_dict(), context="relaunch gate")


@pytest.mark.parametrize(
    "kwargs,expected_decision,expected_gate",
    [
        ({"safety_blocked": True}, RelaunchDecision.BLOCKED_SAFETY, "safety_envelope"),
        ({"daily_risk_scope_status": "DAILY_RISK_SCOPE_MISSING_V2"}, RelaunchDecision.BLOCKED_SCOPE, "daily_risk_scope"),
        ({"clearance_valid": False}, RelaunchDecision.BLOCKED_SCOPE, "clearance"),
        ({"config_valid": False}, RelaunchDecision.BLOCKED_PAPER_STATE, "config_state"),
        ({"data_healthy": False}, RelaunchDecision.BLOCKED_DATA, "data_health"),
        ({"mt5_connected": False}, RelaunchDecision.BLOCKED_DATA, "mt5_connection"),
    ],
)
def test_relaunch_gate_blocks_on_each_input(kwargs: dict, expected_decision: RelaunchDecision, expected_gate: str) -> None:
    state = build_paper_state({"events": [_halt_event(NOW - timedelta(days=1))], "paper_trades": []}, clock=CLOCK)
    call = {"daily_risk_scope_status": "DAILY_RISK_SCOPE_OK_FOR_V2", **kwargs}
    result = evaluate_relaunch(paper_state=state, clock=CLOCK, **call)
    assert result.relaunch_allowed is False
    assert result.decision is expected_decision
    assert expected_gate in result.blocking_gate_ids


def test_safety_flag_blocks_before_any_other_gate_is_considered() -> None:
    state = build_paper_state({"events": [_halt_event(NOW.replace(hour=9))], "paper_trades": [{"paper_trade_id": "o", "status": "OPEN", "entry_price": 1.1, "sl_price": 1.1, "tp_price": 1.2}]}, clock=CLOCK)
    result = evaluate_relaunch(paper_state=state, safety_blocked=True, daily_risk_scope_status="DAILY_RISK_SCOPE_OK_FOR_V2", clock=CLOCK)
    assert result.decision is RelaunchDecision.BLOCKED_SAFETY
    assert result.blocking_gate_ids == ["safety_envelope"]


def test_active_halt_blocks_relaunch() -> None:
    state = build_paper_state({"events": [_halt_event(NOW.replace(hour=9))], "paper_trades": []}, clock=CLOCK)
    result = evaluate_relaunch(paper_state=state, daily_risk_scope_status="DAILY_RISK_SCOPE_OK_FOR_V2", clock=CLOCK)
    assert result.decision is RelaunchDecision.BLOCKED_HALT_ACTIVE
    assert result.evidence_references["halt_timestamp_utc"] == NOW.replace(hour=9).isoformat()


def test_malformed_halt_evidence_blocks_relaunch() -> None:
    dataset = {"events": [_event(event_type="PAPER_DAILY_DRAWDOWN_HALT", timestamp_utc="bad", payload={"halt_reason": "PAPER_DAILY_DRAWDOWN_HALT"})], "paper_trades": []}
    state = build_paper_state(dataset, clock=CLOCK)
    result = evaluate_relaunch(paper_state=state, daily_risk_scope_status="DAILY_RISK_SCOPE_OK_FOR_V2", clock=CLOCK)
    assert result.relaunch_allowed is False
    assert "evidence_quality" in result.blocking_gate_ids


# --------------------------------------------------------------------------- error hierarchy


@pytest.mark.parametrize(
    "error_class,expected_type",
    [
        (DataError, "DATA_ERROR"),
        (TimestampError, "TIMESTAMP_ERROR"),
        (InstrumentError, "INSTRUMENT_ERROR"),
        (ConfigurationError, "CONFIGURATION_ERROR"),
        (RiskError, "RISK_ERROR"),
        (PaperStateError, "PAPER_STATE_ERROR"),
        (ExecutionSimulationError, "EXECUTION_SIMULATION_ERROR"),
        (EvidenceError, "EVIDENCE_ERROR"),
    ],
)
def test_error_hierarchy_records_cause_and_safety(error_class, expected_type: str) -> None:
    record = error_class("something specific went wrong", source="unit_test", clock=CLOCK).as_dict()
    assert record["error_type"] == expected_type
    assert record["message"] == "something specific went wrong"
    assert record["source"] == "unit_test"
    assert record["timestamp_utc"] == NOW.isoformat()
    assert isinstance(record["recoverable"], bool)
    assert_safety_flags(record, context="error record")
    assert issubclass(error_class, OperationalError)


def test_timestamp_error_is_a_data_error() -> None:
    assert issubclass(TimestampError, DataError)


def test_unclassified_exception_keeps_its_own_type_not_config_error() -> None:
    """The whole point: a real fault must not collapse into a generic CONFIG_ERROR."""

    record = error_record(ValueError("paper trade has invalid risk distance"), source="paper_trade_engine", clock=CLOCK)
    assert record["error_type"] == "UNCLASSIFIED_VALUEERROR"
    assert record["error_type"] != "CONFIG_ERROR"
    assert record["message"] == "paper trade has invalid risk distance"
    assert_safety_flags(record, context="unclassified error record")


# --------------------------------------------------------------------------- legacy equivalence


def test_halt_equivalence_has_no_unexplained_difference() -> None:
    report = build_equivalence_report(clock=CLOCK)
    assert report["equivalence_status"] == "EQUIVALENCE_OK"
    assert report["unexplained_difference_count"] == 0
    assert report["comparison_count"] > 0
    for row in report["differences"]:
        assert row["verdict"].startswith(("LEGACY_BEHAVIOR_BUG", "CANONICAL_", "NOT_COMPARABLE"))
    assert_safety_flags(report, context="halt equivalence report")


def test_gate_equivalence_is_exact() -> None:
    report = build_gate_equivalence_report(clock=CLOCK)
    assert report["gate_equivalence_status"] == "GATE_EQUIVALENCE_OK"
    assert report["difference_count"] == 0
    assert report["same_decision_count"] == report["comparison_count"] > 0
    assert_safety_flags(report, context="gate equivalence report")


def test_legacy_reset_readiness_now_delegates_to_the_canonical_detector() -> None:
    """The legacy entry point keeps its vocabulary and returns the canonical verdict."""

    dataset = {"events": [_halt_event(NOW.replace(hour=9)), _halt_event(NOW - timedelta(days=30), source="jsonl:events.jsonl:1")]}
    legacy = audit_daily_halt_status(dataset, current_utc=NOW)
    canonical = detect_halt(dataset, clock=CLOCK)

    assert legacy["daily_halt_active"] == canonical.halt_active is True
    assert legacy["latest_halt_utc"] == canonical.halt_timestamp_utc
    assert legacy["daily_reset_occurred"] == canonical.daily_reset_occurred is False
    assert legacy["halt_kind"] == canonical.halt_kind.value
    assert_safety_flags(legacy, context="legacy reset readiness")


def test_legacy_drawdown_loaders_keep_their_scope_after_delegation() -> None:
    from agi_style_forex_bot_mt5.micro_v2_closed_loss_scope_decision.daily_drawdown_legitimacy_audit import _halt_count
    from agi_style_forex_bot_mt5.micro_v2_daily_drawdown_state_recovery.drawdown_halt_loader import drawdown_halt_events

    dataset = {
        "events": [
            _halt_event(NOW.replace(hour=9)),
            _event(event_type="paper_daily_drawdown_halt", timestamp_utc=NOW.replace(hour=10).isoformat(), payload={"halt_reason": "paper_daily_drawdown_halt"}),
            _event(event_type="FORWARD_SHADOW_CRITICAL_ERROR", timestamp_utc=NOW.replace(hour=11).isoformat(), payload={"halt_reason": "PAPER_STATE_ERROR"}),
        ]
    }
    # Both drawdown halts are found (including the lower-case one the old rule missed);
    # the PAPER_STATE_ERROR halt stays out of scope for these drawdown reports.
    assert len(drawdown_halt_events(dict(dataset))) == 2
    assert _halt_count(dataset) == 2


# --------------------------------------------------------------------------- CLI and safety


def test_unified_operational_state_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from agi_style_forex_bot_mt5.cli import main

    assert main(["--mode", "unified-operational-state", "--output-dir", str(tmp_path / "out")]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["unified_operational_state_status"] == "UNIFIED_OPERATIONAL_STATE_OK"
    assert payload["halt_unexplained_difference_count"] == 0
    assert payload["gate_difference_count"] == 0
    assert payload["run_manifest"]["run_id"]
    assert_safety_flags(payload, context="unified operational state CLI")

    diff = json.loads((tmp_path / "out" / "halt_migration_diff.json").read_text(encoding="utf-8"))
    assert diff["comparisons"]
    gate_diff = json.loads((tmp_path / "out" / "relaunch_gate_migration_diff.json").read_text(encoding="utf-8"))
    assert gate_diff["comparisons"]


def test_report_writes_nothing_into_production_evidence(tmp_path: Path) -> None:
    production = workspace_paths().project_root / "data"
    before = sorted(str(path) for path in production.rglob("*")) if production.exists() else []
    run_unified_operational_state_report(output_dir=tmp_path / "out")
    after = sorted(str(path) for path in production.rglob("*")) if production.exists() else []
    assert before == after


def test_global_safety_defaults_intact() -> None:
    config = load_config(None)
    assert config.demo_only is True
    assert config.live_trading_approved is False
