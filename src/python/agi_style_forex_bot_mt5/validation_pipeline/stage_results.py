"""Validation pipeline stage results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    started_at_utc: str | None
    ended_at_utc: str | None
    duration_seconds: float
    command_or_function: str
    input_paths: tuple[str, ...] = field(default_factory=tuple)
    output_paths: tuple[str, ...] = field(default_factory=tuple)
    summary: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

