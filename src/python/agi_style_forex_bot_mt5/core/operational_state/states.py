"""Canonical operational state vocabulary.

Every name here corresponds to behaviour that already exists somewhere in the
project. Nothing was invented to round out an enum: `HALT_DATA` is the only
entry with no legacy producer yet, and it exists because the detector must be
able to classify malformed evidence as something other than "no halt".
"""

from __future__ import annotations

from enum import Enum


class HaltKind(str, Enum):
    """What kind of halt the evidence describes."""

    NONE = "HALT_NONE"
    DAILY_DRAWDOWN = "HALT_DAILY_DRAWDOWN"          # PAPER_DAILY_DRAWDOWN[_HALT]
    PAPER_STATE = "HALT_PAPER_STATE"                # PAPER_STATE_ERROR
    CONFIG = "HALT_CONFIG"                          # CONFIG_ERROR
    MANUAL = "HALT_MANUAL"                          # SHADOW_MANUALLY_PAUSED / shadow_paused
    DATA = "HALT_DATA"                              # malformed or unusable evidence
    UNKNOWN = "HALT_UNKNOWN"                        # halt asserted with no identifiable cause


class HaltAge(str, Enum):
    """Where the halt sits relative to the current operational day."""

    NONE = "HALT_AGE_NONE"
    ACTIVE = "HALT_AGE_ACTIVE"          # same operational day as the clock (or later)
    HISTORICAL = "HALT_AGE_HISTORICAL"  # an earlier operational day: a daily reset has occurred
    STALE = "HALT_AGE_STALE"            # older than the staleness horizon
    MALFORMED = "HALT_AGE_MALFORMED"    # halt evidence with no usable timestamp


class EvidenceQuality(str, Enum):
    OK = "EVIDENCE_OK"
    PARTIAL = "EVIDENCE_PARTIAL"        # some records unusable, others fine
    MALFORMED = "EVIDENCE_MALFORMED"    # halt asserted but no record is usable
    EMPTY = "EVIDENCE_EMPTY"


class Severity(str, Enum):
    NONE = "NONE"
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class PaperStateStatus(str, Enum):
    OK = "PAPER_STATE_OK"
    OPEN_TRADES = "PAPER_STATE_OPEN_TRADES"
    INVALID_OPEN_TRADES = "PAPER_STATE_INVALID_OPEN_TRADES"
    CONFIG_ERROR = "PAPER_STATE_CONFIG_ERROR"
    STATE_ERROR = "PAPER_STATE_ERROR"
    UNKNOWN = "PAPER_STATE_UNKNOWN"


class RelaunchDecision(str, Enum):
    ALLOWED = "RELAUNCH_ALLOWED"
    BLOCKED_SAFETY = "RELAUNCH_BLOCKED_SAFETY"
    BLOCKED_HALT_ACTIVE = "RELAUNCH_BLOCKED_HALT_ACTIVE"
    BLOCKED_SCOPE = "RELAUNCH_BLOCKED_SCOPE"
    BLOCKED_PAPER_STATE = "RELAUNCH_BLOCKED_PAPER_STATE"
    BLOCKED_OPEN_TRADES = "RELAUNCH_BLOCKED_OPEN_TRADES"
    BLOCKED_INVALID_TRADES = "RELAUNCH_BLOCKED_INVALID_TRADES"
    BLOCKED_DATA = "RELAUNCH_BLOCKED_DATA"


# Severity of each halt kind, and the tie-break order when two halts share a timestamp.
HALT_SEVERITY: dict[HaltKind, Severity] = {
    HaltKind.NONE: Severity.NONE,
    HaltKind.DAILY_DRAWDOWN: Severity.CRITICAL,
    HaltKind.PAPER_STATE: Severity.CRITICAL,
    HaltKind.CONFIG: Severity.CRITICAL,
    HaltKind.MANUAL: Severity.WARNING,
    HaltKind.DATA: Severity.WARNING,
    HaltKind.UNKNOWN: Severity.WARNING,
}

HALT_PRECEDENCE: tuple[HaltKind, ...] = (
    HaltKind.PAPER_STATE,
    HaltKind.CONFIG,
    HaltKind.DAILY_DRAWDOWN,
    HaltKind.MANUAL,
    HaltKind.DATA,
    HaltKind.UNKNOWN,
    HaltKind.NONE,
)
