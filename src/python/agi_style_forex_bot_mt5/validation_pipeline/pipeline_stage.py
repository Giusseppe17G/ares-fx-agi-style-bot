"""Validation pipeline stage definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class StageStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


StageFunction = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class PipelineStage:
    name: str
    enabled: bool
    function: StageFunction
    expected_outputs: tuple[Path, ...] = field(default_factory=tuple)
    input_paths: tuple[Path, ...] = field(default_factory=tuple)
    required: bool = True
    command_or_function: str = ""

