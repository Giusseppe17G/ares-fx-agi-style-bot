"""Canonical paper state.

One representation of open/closed/quarantined trades, PnL, daily risk, halt and
config state. The three legacy repair modules (paper_state_schema_repair,
micro_v2_papertrade_schema_repair, micro_v2_guarded_paper_state_repair) keep
their own reports; this is the shared model they can all be read through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..clock import Clock, resolve_clock
from ..safety import SafetyEnvelope
from .halt_detector import HaltAssessment, detect_halt
from .states import PaperStateStatus


@dataclass(frozen=True)
class PaperTradeView:
    """A trade reduced to the fields every consumer actually reads."""

    paper_trade_id: str
    symbol: str
    status: str
    entry_price: float | None
    sl_price: float | None
    tp_price: float | None
    pnl: float
    opened_at_utc: str
    closed_at_utc: str

    @property
    def is_open(self) -> bool:
        return self.status.upper() == "OPEN"

    @property
    def is_quarantined(self) -> bool:
        return "QUARANTINED" in self.status.upper()

    @property
    def is_closed(self) -> bool:
        return self.status.upper() in {"CLOSED", "CLOSED_PAPER", "PAPER_CLOSED"}

    @property
    def has_invalid_risk_distance(self) -> bool:
        """The FASE 64-69 defect: an open trade whose stop or target equals entry."""

        if self.entry_price is None or self.sl_price is None or self.tp_price is None:
            return True
        return abs(self.entry_price - self.sl_price) <= 1e-12 or abs(self.tp_price - self.entry_price) <= 1e-12


@dataclass(frozen=True)
class PaperState:
    """The canonical operational picture of paper trading."""

    status: PaperStateStatus
    open_trades: Sequence[PaperTradeView]
    closed_trades: Sequence[PaperTradeView]
    quarantined_trades: Sequence[PaperTradeView]
    invalid_open_trades: Sequence[PaperTradeView]
    closed_pnl: float
    daily_drawdown: float
    daily_drawdown_limit: float
    halt: HaltAssessment
    latest_exit_reason: str
    config_error_active: bool
    paper_state_error_active: bool
    block_new_entries: bool
    records: Mapping[str, Any] = field(default_factory=dict)

    @property
    def clean_for_relaunch(self) -> bool:
        return (
            self.status is PaperStateStatus.OK
            and not self.open_trades
            and not self.invalid_open_trades
            and not self.config_error_active
            and not self.paper_state_error_active
        )

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "paper_state_status": self.status.value,
            "open_trade_count": len(self.open_trades),
            "closed_trade_count": len(self.closed_trades),
            "quarantined_trade_count": len(self.quarantined_trades),
            "invalid_open_trade_count": len(self.invalid_open_trades),
            "closed_pnl": round(self.closed_pnl, 6),
            "daily_drawdown": round(self.daily_drawdown, 6),
            "daily_drawdown_limit": self.daily_drawdown_limit,
            "latest_exit_reason": self.latest_exit_reason,
            "config_error_active": self.config_error_active,
            "paper_state_error_active": self.paper_state_error_active,
            "block_new_entries": self.block_new_entries,
            "paper_state_clean_for_relaunch": self.clean_for_relaunch,
            "halt_active": self.halt.halt_active,
            "halt_kind": self.halt.halt_kind.value,
            "halt_reason": self.halt.halt_reason,
            "daily_reset_occurred": self.halt.daily_reset_occurred,
        }
        return SafetyEnvelope().seal(payload)


def build_paper_state(
    dataset: Mapping[str, Any] | None = None,
    *,
    trades: Sequence[Mapping[str, Any]] | None = None,
    operational_state: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    daily_drawdown_limit: float = -3.0,
    clock: Clock | None = None,
) -> PaperState:
    resolved_clock = resolve_clock(clock)
    raw_trades = list(trades) if trades is not None else list((dataset or {}).get("paper_trades", []))
    views = [_view(trade) for trade in raw_trades if isinstance(trade, Mapping)]
    open_trades = [view for view in views if view.is_open]
    quarantined = [view for view in views if view.is_quarantined]
    closed = [view for view in views if view.is_closed]
    invalid_open = [view for view in open_trades if view.has_invalid_risk_distance]

    state = operational_state
    if state is None and dataset:
        candidate = dataset.get("operational_state")
        state = candidate if isinstance(candidate, Mapping) else {}
    state = state if isinstance(state, Mapping) else {}

    halt = detect_halt(dataset, operational_state=state, metrics=metrics, clock=resolved_clock, daily_drawdown_limit=daily_drawdown_limit)
    latest_exit_reason = str(state.get("latest_exit_reason") or "")
    config_error = latest_exit_reason.upper() == "CONFIG_ERROR"
    paper_state_error = str(state.get("halt_reason") or state.get("paused_reason") or "").upper() == "PAPER_STATE_ERROR"
    closed_pnl = sum(view.pnl for view in closed)
    daily_drawdown = _float(
        (metrics or {}).get("daily_drawdown_shadow")
        if metrics
        else (dataset or {}).get("daily_drawdown_shadow"),
        default=min(closed_pnl, 0.0),
    )

    if paper_state_error:
        status = PaperStateStatus.STATE_ERROR
    elif config_error:
        status = PaperStateStatus.CONFIG_ERROR
    elif invalid_open:
        status = PaperStateStatus.INVALID_OPEN_TRADES
    elif open_trades:
        status = PaperStateStatus.OPEN_TRADES
    else:
        status = PaperStateStatus.OK

    return PaperState(
        status=status,
        open_trades=tuple(open_trades),
        closed_trades=tuple(closed),
        quarantined_trades=tuple(quarantined),
        invalid_open_trades=tuple(invalid_open),
        closed_pnl=closed_pnl,
        daily_drawdown=daily_drawdown,
        daily_drawdown_limit=daily_drawdown_limit,
        halt=halt,
        latest_exit_reason=latest_exit_reason,
        config_error_active=config_error,
        paper_state_error_active=paper_state_error,
        block_new_entries=bool(_truthy(state.get("block_new_entries")) or halt.halt_active),
        records={"trade_count": len(views)},
    )


def _view(trade: Mapping[str, Any]) -> PaperTradeView:
    return PaperTradeView(
        paper_trade_id=str(trade.get("paper_trade_id") or trade.get("id") or ""),
        symbol=str(trade.get("symbol") or ""),
        status=str(trade.get("status") or ""),
        entry_price=_optional_float(trade.get("entry_price") or trade.get("open_price") or trade.get("price")),
        sl_price=_optional_float(trade.get("sl_price") or trade.get("stop_loss") or trade.get("sl")),
        tp_price=_optional_float(trade.get("tp_price") or trade.get("take_profit") or trade.get("tp")),
        pnl=_float(trade.get("pnl") if trade.get("pnl") is not None else trade.get("profit"), default=0.0),
        opened_at_utc=str(trade.get("opened_at_utc") or trade.get("entry_time_utc") or ""),
        closed_at_utc=str(trade.get("closed_at_utc") or trade.get("exit_time_utc") or ""),
    )


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any, *, default: float = 0.0) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
