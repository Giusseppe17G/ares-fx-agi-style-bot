"""Portfolio guard for shadow/paper candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .currency_exposure import calculate_currency_exposure


@dataclass(frozen=True)
class PortfolioGuardDecision:
    accepted: bool
    reject_code: str
    reject_reason: str
    risk_multiplier: float
    checks: dict[str, Any]
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PortfolioGuard:
    def __init__(
        self,
        *,
        max_open_trades: int = 10,
        max_trades_per_symbol: int = 2,
        max_open_risk_pct: float = 5.0,
        max_currency_exposure_pct: float = 2.0,
        max_usd_exposure_pct: float = 3.0,
        max_strategy_concentration: int = 5,
        max_regime_concentration: int = 6,
    ) -> None:
        self.max_open_trades = max_open_trades
        self.max_trades_per_symbol = max_trades_per_symbol
        self.max_open_risk_pct = max_open_risk_pct
        self.max_currency_exposure_pct = max_currency_exposure_pct
        self.max_usd_exposure_pct = max_usd_exposure_pct
        self.max_strategy_concentration = max_strategy_concentration
        self.max_regime_concentration = max_regime_concentration

    def evaluate(
        self,
        *,
        candidate: Mapping[str, Any],
        open_trades: Sequence[Mapping[str, Any]],
        correlation: float | None = None,
        shadow_paused: bool = False,
        daily_drawdown_pct: float = 0.0,
        consecutive_losses: int = 0,
    ) -> PortfolioGuardDecision:
        checks: dict[str, Any] = {"shadow_paused": shadow_paused}
        symbol = str(candidate.get("symbol") or "")
        risk_pct = float(candidate.get("risk_pct") or 0.0)
        projected = [*open_trades, candidate]
        exposure = calculate_currency_exposure(projected, max_currency_exposure_pct=self.max_currency_exposure_pct, max_usd_exposure_pct=self.max_usd_exposure_pct)
        open_risk = sum(float(trade.get("risk_pct") or 0.0) for trade in open_trades) + risk_pct
        symbol_count = sum(1 for trade in open_trades if str(trade.get("symbol")) == symbol)
        strategy = str(candidate.get("strategy_name") or "")
        regime = str(candidate.get("regime") or "")
        strategy_count = sum(1 for trade in open_trades if str(trade.get("strategy_name")) == strategy)
        regime_count = sum(1 for trade in open_trades if str(trade.get("regime")) == regime)
        checks.update(
            {
                "open_trades": len(open_trades),
                "symbol_count": symbol_count,
                "open_risk_pct_after": open_risk,
                "currency_exposure": exposure.to_dict(),
                "correlation": correlation,
                "strategy_count": strategy_count,
                "regime_count": regime_count,
                "daily_drawdown_pct": daily_drawdown_pct,
                "consecutive_losses": consecutive_losses,
            }
        )
        if shadow_paused:
            return self._reject("SHADOW_PAUSED", "shadow entries are paused", checks)
        if len(open_trades) >= self.max_open_trades:
            return self._reject("MAX_OPEN_TRADES", "max open paper trades reached", checks)
        if symbol_count >= self.max_trades_per_symbol:
            return self._reject("MAX_TRADES_PER_SYMBOL", "max paper trades for symbol reached", checks)
        if open_risk > self.max_open_risk_pct:
            return self._reject("MAX_OPEN_RISK", "portfolio risk budget exceeded", checks)
        if exposure.breaches:
            return self._reject("CURRENCY_EXPOSURE_HIGH", "currency exposure limit exceeded", checks)
        if correlation is not None and abs(correlation) > 0.85:
            return self._reject("CORRELATION_CLUSTER_HIGH", "candidate is highly correlated with open exposure", checks)
        if strategy_count >= self.max_strategy_concentration:
            return self._reject("STRATEGY_CONCENTRATION_HIGH", "strategy concentration is high", checks)
        if regime_count >= self.max_regime_concentration:
            return self._reject("REGIME_CONCENTRATION_HIGH", "regime concentration is high", checks)
        if daily_drawdown_pct >= 3.0:
            return self._reject("PAPER_DRAWDOWN_LIMIT", "paper daily drawdown limit reached", checks)
        if consecutive_losses >= 4:
            return self._reject("LOSS_STREAK_LIMIT", "recent loss streak too high", checks)
        return PortfolioGuardDecision(True, "", "", 1.0, checks, False)

    def _reject(self, code: str, reason: str, checks: dict[str, Any]) -> PortfolioGuardDecision:
        return PortfolioGuardDecision(False, code, reason, 0.0, checks, False)

