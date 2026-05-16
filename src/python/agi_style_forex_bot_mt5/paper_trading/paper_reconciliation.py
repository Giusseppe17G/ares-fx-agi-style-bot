"""Paper reconciliation helpers."""

from __future__ import annotations

from .paper_trade import PaperTrade


def reconcile_open_trades(trades: tuple[PaperTrade, ...]) -> dict[str, int]:
    return {"open_trades": len([trade for trade in trades if trade.status == "OPEN"])}
