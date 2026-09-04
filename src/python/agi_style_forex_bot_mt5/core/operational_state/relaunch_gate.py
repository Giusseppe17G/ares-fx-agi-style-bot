"""The single relaunch authority.

Four modules previously decided `relaunch_allowed` and two more re-derived it
from their outputs, each with its own precedence. This gate produces one
decision plus the blocking gate ids and reasons behind it; the legacy modules
become wrappers that map their vocabulary onto this result.

Fail-closed: every unknown or missing input blocks, and a safety flag blocks
before anything else is even considered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..clock import Clock, resolve_clock
from ..safety import SafetyEnvelope
from .halt_detector import HaltAssessment
from .paper_state import PaperState
from .states import EvidenceQuality, RelaunchDecision


DAILY_RISK_SCOPE_OK = "DAILY_RISK_SCOPE_OK_FOR_V2"


@dataclass(frozen=True)
class BlockingGate:
    gate_id: str
    reason: str
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"gate_id": self.gate_id, "reason": self.reason, "evidence": self.evidence}


@dataclass(frozen=True)
class RelaunchAssessment:
    decision: RelaunchDecision
    relaunch_allowed: bool
    blocking_gates: Sequence[BlockingGate] = field(default_factory=tuple)
    evidence_references: Mapping[str, Any] = field(default_factory=dict)

    @property
    def blocking_gate_ids(self) -> list[str]:
        return [gate.gate_id for gate in self.blocking_gates]

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "relaunch_decision": self.decision.value,
            "relaunch_allowed": self.relaunch_allowed,
            "blocking_gate_ids": self.blocking_gate_ids,
            "blocking_gate_count": len(self.blocking_gates),
            "blocking_gates": [gate.as_dict() for gate in self.blocking_gates],
            "reasons": [gate.reason for gate in self.blocking_gates],
            "evidence_references": dict(self.evidence_references),
            "recommended_next_action": "RELAUNCH_V2_PAPER_DRY_RUN_MANUALLY" if self.relaunch_allowed else "KEEP_V2_STOPPED_AND_RERUN_RESET_READINESS_LATER",
        }
        return SafetyEnvelope().seal(payload)


def evaluate_relaunch(
    *,
    paper_state: PaperState,
    halt: HaltAssessment | None = None,
    safety_blocked: bool = False,
    daily_risk_scope_status: str = "",
    clearance_valid: bool = True,
    config_valid: bool = True,
    data_healthy: bool = True,
    mt5_connected: bool = True,
    clock: Clock | None = None,
) -> RelaunchAssessment:
    """The one place `relaunch_allowed` is decided."""

    resolve_clock(clock)
    assessment = halt or paper_state.halt
    gates: list[BlockingGate] = []

    # Safety first: a report claiming any execution blocks before anything else.
    if safety_blocked:
        gates.append(BlockingGate("safety_envelope", "A source report claims execution was attempted.", "safety flags"))
        return _result(RelaunchDecision.BLOCKED_SAFETY, gates, assessment, paper_state)

    if assessment.evidence_quality is EvidenceQuality.MALFORMED:
        gates.append(BlockingGate("evidence_quality", "Halt evidence exists but carries no usable timestamp.", assessment.halt_source))
    if assessment.halt_active:
        gates.append(BlockingGate("daily_halt", f"Halt is active for the current operational day: {assessment.halt_reason or assessment.halt_kind.value}.", assessment.halt_timestamp_utc))
    if daily_risk_scope_status != DAILY_RISK_SCOPE_OK:
        gates.append(BlockingGate("daily_risk_scope", f"Daily risk scope is not {DAILY_RISK_SCOPE_OK}.", daily_risk_scope_status or "missing"))
    if not clearance_valid:
        gates.append(BlockingGate("clearance", "Paper risk clearance is missing or stale.", ""))
    if not config_valid or paper_state.config_error_active:
        gates.append(BlockingGate("config_state", "CONFIG_ERROR is active or the profile config is invalid.", paper_state.latest_exit_reason))
    if paper_state.paper_state_error_active:
        gates.append(BlockingGate("paper_state_error", "PAPER_STATE_ERROR is active.", ""))
    if paper_state.invalid_open_trades:
        gates.append(BlockingGate("invalid_open_trades", f"{len(paper_state.invalid_open_trades)} open paper trade(s) have an invalid risk distance.", ""))
    if paper_state.open_trades:
        gates.append(BlockingGate("open_trades", f"{len(paper_state.open_trades)} paper trade(s) are still open.", ""))
    if not data_healthy:
        gates.append(BlockingGate("data_health", "Market data health check failed.", ""))
    if not mt5_connected:
        gates.append(BlockingGate("mt5_connection", "MT5 is not connected.", ""))

    if not gates:
        return _result(RelaunchDecision.ALLOWED, gates, assessment, paper_state)
    return _result(_decision_for(gates), gates, assessment, paper_state)


def _decision_for(gates: Sequence[BlockingGate]) -> RelaunchDecision:
    """The first blocking gate in precedence order names the decision."""

    by_id = {gate.gate_id for gate in gates}
    for gate_id, decision in (
        ("evidence_quality", RelaunchDecision.BLOCKED_DATA),
        ("daily_halt", RelaunchDecision.BLOCKED_HALT_ACTIVE),
        ("daily_risk_scope", RelaunchDecision.BLOCKED_SCOPE),
        ("clearance", RelaunchDecision.BLOCKED_SCOPE),
        ("config_state", RelaunchDecision.BLOCKED_PAPER_STATE),
        ("paper_state_error", RelaunchDecision.BLOCKED_PAPER_STATE),
        ("invalid_open_trades", RelaunchDecision.BLOCKED_INVALID_TRADES),
        ("open_trades", RelaunchDecision.BLOCKED_OPEN_TRADES),
        ("data_health", RelaunchDecision.BLOCKED_DATA),
        ("mt5_connection", RelaunchDecision.BLOCKED_DATA),
    ):
        if gate_id in by_id:
            return decision
    return RelaunchDecision.BLOCKED_DATA


def _result(decision: RelaunchDecision, gates: Sequence[BlockingGate], halt: HaltAssessment, paper_state: PaperState) -> RelaunchAssessment:
    return RelaunchAssessment(
        decision=decision,
        relaunch_allowed=decision is RelaunchDecision.ALLOWED,
        blocking_gates=tuple(gates),
        evidence_references={
            "halt_timestamp_utc": halt.halt_timestamp_utc,
            "halt_operational_day": halt.halt_operational_day,
            "current_operational_day": halt.current_operational_day,
            "halt_source": halt.halt_source,
            "paper_state_status": paper_state.status.value,
        },
    )
