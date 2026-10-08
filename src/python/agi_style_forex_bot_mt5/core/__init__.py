"""Cross-cutting invariants: safety contract, workspace roots, clock, provenance."""

from .clock import SYSTEM_CLOCK, Clock, FrozenClock, SystemClock, resolve_clock
from .run_manifest import MANIFEST_VERSION, RunManifest, hash_config, hash_paths, redact_mapping
from .safety import (
    FULL_SAFETY_FLAGS,
    PAPER_ONLY,
    REQUIRED_SAFETY_FLAGS,
    SafetyEnvelope,
    SafetyInvariantError,
    assert_safety_flags,
    missing_safety_flags,
    seal_report,
)
from .workspace import DATA_ROOT_ENV, PROJECT_ROOT_ENV, WorkspacePaths, workspace_paths

__all__ = [
    "SYSTEM_CLOCK",
    "Clock",
    "FrozenClock",
    "SystemClock",
    "resolve_clock",
    "MANIFEST_VERSION",
    "RunManifest",
    "hash_config",
    "hash_paths",
    "redact_mapping",
    "FULL_SAFETY_FLAGS",
    "PAPER_ONLY",
    "REQUIRED_SAFETY_FLAGS",
    "SafetyEnvelope",
    "SafetyInvariantError",
    "assert_safety_flags",
    "missing_safety_flags",
    "seal_report",
    "DATA_ROOT_ENV",
    "PROJECT_ROOT_ENV",
    "WorkspacePaths",
    "workspace_paths",
]
