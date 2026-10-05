"""Shared, paper-only decision orchestration; never an execution adapter."""

from .pipeline import DecisionContext, PipelineDecision, SharedDecisionPipeline, StageTrace
from .signal_builder import build_signal_prices, build_trade_signal

__all__ = ["DecisionContext", "PipelineDecision", "SharedDecisionPipeline", "StageTrace", "build_signal_prices", "build_trade_signal"]
