"""Replay recorded decision inputs through the production decision core.

This validates decisions, not returns. Each record supplies the complete book
and its observation time; this adapter does not fabricate an empty portfolio or
present independent candidate simulations as a stateful portfolio backtest.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Iterable

from ..core.clock import FrozenClock
from ..core.decision import DecisionContext, PipelineDecision, SharedDecisionPipeline


@dataclass(frozen=True)
class RecordedDecision:
    decision_time_utc: datetime
    context: DecisionContext


@dataclass(frozen=True)
class DecisionReplayResult:
    decisions: tuple[PipelineDecision, ...]
    audit_complete: bool
    scope: str = "RECORDED_DECISION_REPLAY"
    full_pipeline_verified: bool = False
    performance_verified: bool = False
    execution_attempted: bool = False


def replay_decisions(
    records: Iterable[RecordedDecision], *, pipeline: SharedDecisionPipeline,
    clock: FrozenClock, persist_decision: Callable[[PipelineDecision], bool],
) -> DecisionReplayResult:
    """Require causal ordering and durable result audit for every decision.

    The pipeline persists each directional signal before risk evaluation. This
    adapter then persists the entire result before returning an acceptance. A
    storage error halts the replay and revokes the last accepted decision.
    """
    if not isinstance(clock, FrozenClock) or pipeline.clock is not clock:
        raise ValueError("decision replay requires the pipeline's injected FrozenClock")
    results: list[PipelineDecision] = []
    previous: datetime | None = None
    identities: set[str] = set()
    for record in records:
        instant = record.decision_time_utc
        if not isinstance(instant, datetime) or instant.utcoffset() is None:
            raise ValueError("recorded decision time must be timezone-aware")
        instant = instant.astimezone(timezone.utc)
        if previous is not None and instant < previous:
            raise ValueError("recorded decisions must be chronological")
        if record.context.decision_id in identities:
            raise ValueError("duplicate recorded decision identity")
        identities.add(record.context.decision_id)
        previous = instant
        clock.instant = instant
        decision = pipeline.evaluate(record.context)
        try:
            stored = persist_decision(decision) is True
        except Exception:
            stored = False
        if not stored:
            risk = decision.risk_decision
            if risk is not None:
                risk = replace(risk, accepted=False, approved_lot=0.0, risk_amount_account_currency=0.0,
                               reject_code="DECISION_AUDIT_FAILED", reject_reason="decision result was not durably stored")
            decision = replace(decision, accepted=False, reject_code="DECISION_AUDIT_FAILED",
                               reject_reason="decision result was not durably stored", risk_decision=risk)
            results.append(decision)
            return DecisionReplayResult(tuple(results), audit_complete=False)
        results.append(decision)
    return DecisionReplayResult(tuple(results), audit_complete=bool(results))
