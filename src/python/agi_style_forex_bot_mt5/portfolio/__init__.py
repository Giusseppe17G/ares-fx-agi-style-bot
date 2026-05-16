"""Portfolio intelligence for shadow/paper trading."""

from .correlation_matrix import build_correlation_report, compute_correlation_matrix
from .currency_exposure import CurrencyExposure, calculate_currency_exposure, projected_trade_exposure
from .dynamic_risk_allocator import DynamicRiskAllocator, DynamicRiskDecision
from .exposure_report import build_exposure_report
from .portfolio_guard import PortfolioGuard, PortfolioGuardDecision
from .portfolio_report import build_portfolio_status
from .portfolio_state import PortfolioState, build_portfolio_state
from .signal_ranker import SignalRanker

__all__ = [
    "CurrencyExposure",
    "DynamicRiskAllocator",
    "DynamicRiskDecision",
    "PortfolioGuard",
    "PortfolioGuardDecision",
    "PortfolioState",
    "SignalRanker",
    "build_correlation_report",
    "build_exposure_report",
    "build_portfolio_status",
    "build_portfolio_state",
    "calculate_currency_exposure",
    "compute_correlation_matrix",
    "projected_trade_exposure",
]
