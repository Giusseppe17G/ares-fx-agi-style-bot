"""Central safety contract for every report, gate and audit in the project.

The project asserts the same five safety facts in hundreds of places by copying
literal booleans into report dictionaries. Copies cannot enforce anything: a new
module that forgets a flag produces a report that silently claims nothing. This
module owns the facts instead, refuses to represent a contradictory combination,
and provides the assertions that gate/acceptance tests use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


REQUIRED_SAFETY_FLAGS = ("execution_attempted", "order_send_called", "order_check_called")
FULL_SAFETY_FLAGS = REQUIRED_SAFETY_FLAGS + ("demo_only", "live_trading_approved")


class SafetyInvariantError(AssertionError):
    """Raised when a payload violates the project safety contract."""


@dataclass(frozen=True)
class SafetyEnvelope:
    """An internally consistent statement of the project safety facts.

    Two implications are enforced at construction time because they are true by
    definition, not by policy:

    * calling ``order_send``/``order_check`` *is* an execution attempt;
    * approving live trading contradicts demo-only operation.

    The stronger project rule -- that nothing may be executed at all -- is not
    baked into the type (a future demo-execution mode would still be a valid
    envelope); it is asserted explicitly via :meth:`require_paper_only`.
    """

    execution_attempted: bool = False
    order_send_called: bool = False
    order_check_called: bool = False
    demo_only: bool = True
    live_trading_approved: bool = False

    def __post_init__(self) -> None:
        for field in FULL_SAFETY_FLAGS:
            if not isinstance(getattr(self, field), bool):
                raise SafetyInvariantError(f"{field} must be a bool, got {type(getattr(self, field)).__name__}")
        if (self.order_send_called or self.order_check_called) and not self.execution_attempted:
            raise SafetyInvariantError("order_send_called/order_check_called imply execution_attempted")
        if self.live_trading_approved and self.demo_only:
            raise SafetyInvariantError("live_trading_approved contradicts demo_only")

    @property
    def paper_only(self) -> bool:
        """True when nothing was executed and live trading is not approved."""

        return not (self.execution_attempted or self.order_send_called or self.order_check_called) and self.demo_only and not self.live_trading_approved

    def require_paper_only(self, *, context: str = "report") -> "SafetyEnvelope":
        if not self.paper_only:
            raise SafetyInvariantError(f"{context} is not paper-only: {self.as_dict()}")
        return self

    def as_dict(self) -> dict[str, bool]:
        return {field: bool(getattr(self, field)) for field in FULL_SAFETY_FLAGS}

    def seal(self, payload: Mapping[str, Any] | None = None, *, full: bool = False) -> dict[str, Any]:
        """Return ``payload`` with the safety facts stamped onto it.

        The envelope always wins: a payload carrying a contradictory flag is
        corrected rather than trusted, so a stale copied literal can never
        outrank the envelope that sealed the report.
        """

        sealed = dict(payload or {})
        flags = self.as_dict()
        keys = FULL_SAFETY_FLAGS if full else REQUIRED_SAFETY_FLAGS
        for key in keys:
            sealed[key] = flags[key]
        return sealed

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SafetyEnvelope":
        """Build an envelope from an existing report, defaulting missing flags to safe values."""

        return cls(
            execution_attempted=_as_bool(payload.get("execution_attempted", False)),
            order_send_called=_as_bool(payload.get("order_send_called", False)),
            order_check_called=_as_bool(payload.get("order_check_called", False)),
            demo_only=_as_bool(payload.get("demo_only", True)),
            live_trading_approved=_as_bool(payload.get("live_trading_approved", False)),
        )

    @classmethod
    def from_config(cls, config: Any) -> "SafetyEnvelope":
        """Build a paper-only envelope reflecting a :class:`BotConfig`-like object."""

        return cls(
            demo_only=_as_bool(getattr(config, "demo_only", True)),
            live_trading_approved=_as_bool(getattr(config, "live_trading_approved", False)),
        )


PAPER_ONLY = SafetyEnvelope()


def seal_report(payload: Mapping[str, Any] | None = None, *, envelope: SafetyEnvelope | None = None, full: bool = False) -> dict[str, Any]:
    """Stamp the paper-only safety facts onto a report payload."""

    return (envelope or PAPER_ONLY).seal(payload, full=full)


def missing_safety_flags(payload: Mapping[str, Any], *, required: Iterable[str] = REQUIRED_SAFETY_FLAGS) -> list[str]:
    return [flag for flag in required if flag not in payload]


def assert_safety_flags(payload: Mapping[str, Any], *, context: str = "report", required: Iterable[str] = REQUIRED_SAFETY_FLAGS) -> SafetyEnvelope:
    """Assert a report declares the mandatory flags and that they are paper-only.

    This is the assertion gate/acceptance tests call: a report that omits a flag
    fails here instead of quietly claiming nothing.
    """

    missing = missing_safety_flags(payload, required=required)
    if missing:
        raise SafetyInvariantError(f"{context} is missing mandatory safety flags: {sorted(missing)}")
    return SafetyEnvelope.from_mapping(payload).require_paper_only(context=context)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False
