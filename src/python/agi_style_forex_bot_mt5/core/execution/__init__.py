"""Execution assumptions shared by backtest and paper trading."""

from .shared_fill import REPLAY_CONTEXT, SharedFillModel

__all__ = ["REPLAY_CONTEXT", "SharedFillModel"]
