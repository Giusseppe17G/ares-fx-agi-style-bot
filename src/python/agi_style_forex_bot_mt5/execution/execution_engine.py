"""Compatibility facade for broker execution, disabled in this release.

Only read-only MT5 data and paper execution have a supported runtime path.
Caller-provided risk decisions, audit booleans and promotion metadata do not
constitute durable, independently verified permission to execute broker orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import ExecutionResult, RiskDecision, TradeSignal, utc_now
from agi_style_forex_bot_mt5.execution.broker_quality import BrokerQualityMonitor
from agi_style_forex_bot_mt5.execution.mt5_connector import MT5Connector
from agi_style_forex_bot_mt5.execution.release_policy import execution_block_reason
from agi_style_forex_bot_mt5.execution.spread_filter import SpreadFilter


@dataclass
class ExecutionEngine:
    """Preserve the API while denying all broker execution before client access."""

    config: BotConfig
    connector: MT5Connector
    spread_filter: SpreadFilter | None = None
    broker_quality: BrokerQualityMonitor = field(default_factory=BrokerQualityMonitor)
    max_retries: int = 1
    _seen_signal_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.spread_filter is None:
            self.spread_filter = SpreadFilter(self.config)

    def execute(
        self,
        *,
        signal: TradeSignal,
        risk_decision: RiskDecision,
        audit_confirmed: bool,
        magic_number: int,
        max_slippage_points: int = 10,
        comment_prefix: str = "agi",
    ) -> ExecutionResult:
        """Reject without constructing requests, consulting MT5 or retrying."""
        code, reason = execution_block_reason(self.config)
        return ExecutionResult(
            signal_id=signal.signal_id, sent=False, filled=False, retcode=0,
            retcode_description=code, timestamp_utc=utc_now(), error_message=reason,
        )
