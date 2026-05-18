"""Forward shadow paper trading lifecycle."""

from .forward_drift_detector import detect_forward_drift
from .forward_stable_drift_detector import detect_stable_forward_drift
from .forward_shadow_bot import ForwardShadowBot, ForwardShadowSummary, forward_summary_to_json
from .paper_fill_model import PaperFillModel
from .paper_performance import group_metrics, paper_metrics
from .paper_position_manager import PaperPositionManager
from .paper_report import write_forward_shadow_report
from .paper_trade import PaperTrade
from .stable_shadow_report import build_stable_health, write_stable_shadow_daily_report

__all__ = [
    "ForwardShadowBot",
    "ForwardShadowSummary",
    "PaperFillModel",
    "PaperPositionManager",
    "PaperTrade",
    "detect_forward_drift",
    "detect_stable_forward_drift",
    "forward_summary_to_json",
    "group_metrics",
    "paper_metrics",
    "write_forward_shadow_report",
    "write_stable_shadow_daily_report",
    "build_stable_health",
]
