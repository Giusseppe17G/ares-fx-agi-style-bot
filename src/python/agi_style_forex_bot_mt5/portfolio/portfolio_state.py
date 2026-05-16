"""Portfolio state consolidation from paper trades."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .currency_exposure import calculate_currency_exposure


@dataclass(frozen=True)
class PortfolioState:
    portfolio_risk_pct: float
    available_risk_budget_pct: float
    currency_exposure: dict[str, Any]
    concentration_flags: list[str]
    recommended_action: str
    open_trades: int
    shadow_paused: bool
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_portfolio_state(database: TelemetryDatabase, *, max_open_risk_pct: float = 5.0) -> PortfolioState:
    open_trades = [json.loads(row["payload_json"]) for row in database.fetch_open_paper_trades()]
    risk = sum(float(trade.get("risk_pct") or 0.0) for trade in open_trades)
    exposure = calculate_currency_exposure(open_trades).to_dict()
    flags: list[str] = []
    if exposure.get("breaches"):
        flags.append("CURRENCY_EXPOSURE_HIGH")
    if risk >= max_open_risk_pct * 0.8:
        flags.append("PORTFOLIO_RISK_BUDGET_LOW")
    shadow_paused = database.get_shadow_paused()
    action = "PAUSE_NEW_ENTRIES" if flags or shadow_paused else "ALLOW_SHADOW_REVIEW"
    return PortfolioState(
        portfolio_risk_pct=risk,
        available_risk_budget_pct=max(0.0, max_open_risk_pct - risk),
        currency_exposure=exposure,
        concentration_flags=flags,
        recommended_action=action,
        open_trades=len(open_trades),
        shadow_paused=shadow_paused,
        execution_attempted=False,
    )

