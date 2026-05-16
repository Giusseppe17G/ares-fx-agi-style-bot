"""Read-only latency assumptions for simulated execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class LatencyEstimate:
    decision_to_fill_delay_ms: float
    data_read_latency_ms: float
    assumed_execution_latency_ms: float
    delay_mode: str
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LatencyModel:
    def __init__(self, *, assumed_execution_latency_ms: float = 250.0, delay_mode: str = "tick") -> None:
        self.assumed_execution_latency_ms = max(0.0, assumed_execution_latency_ms)
        self.delay_mode = delay_mode

    def estimate(self, context: Mapping[str, Any] | None = None) -> LatencyEstimate:
        context = dict(context or {})
        data_latency = float(context.get("data_read_latency_ms") or 0.0)
        decision_delay = data_latency + self.assumed_execution_latency_ms
        return LatencyEstimate(decision_delay, data_latency, self.assumed_execution_latency_ms, self.delay_mode, False)

