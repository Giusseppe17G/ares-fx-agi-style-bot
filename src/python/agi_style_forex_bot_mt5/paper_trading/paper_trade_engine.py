"""Paper trade engine facade."""

from __future__ import annotations

from .paper_position_manager import PaperPositionManager


class PaperTradeEngine:
    """Thin facade around PaperPositionManager for future orchestration."""

    def __init__(self, manager: PaperPositionManager) -> None:
        self.manager = manager
