"""Backtesting and validation tools for AGI_STYLE_FOREX_BOT_MT5."""

from .backtester import (
    Backtester,
    BacktestBatchResult,
    BacktestMetrics,
    BacktestOutcome,
    BacktestSettings,
    CostModel,
    DataQualityReport,
    PromotionGateResult,
    TradeCandidate,
    TradeResult,
    calculate_metrics,
    classify_strategy_promotion,
    load_historical_csv,
    run_backtest_for_symbols,
    run_strategy_backtest,
)
from .monte_carlo import MonteCarloResult, MonteCarloSimulator, monte_carlo_metrics
from .performance_report import PerformanceReportWriter, ReportArtifacts, write_batch_reports, write_reports
from .stress_tester import StressResult, StressTester
from .walk_forward_optimizer import WalkForwardFold, WalkForwardOptimizer, WalkForwardResult

__all__ = [
    "Backtester",
    "BacktestBatchResult",
    "BacktestMetrics",
    "BacktestOutcome",
    "BacktestSettings",
    "CostModel",
    "DataQualityReport",
    "MonteCarloResult",
    "MonteCarloSimulator",
    "PerformanceReportWriter",
    "PromotionGateResult",
    "ReportArtifacts",
    "StressResult",
    "StressTester",
    "TradeCandidate",
    "TradeResult",
    "WalkForwardFold",
    "WalkForwardOptimizer",
    "WalkForwardResult",
    "calculate_metrics",
    "classify_strategy_promotion",
    "load_historical_csv",
    "monte_carlo_metrics",
    "run_backtest_for_symbols",
    "run_strategy_backtest",
    "write_batch_reports",
    "write_reports",
]
