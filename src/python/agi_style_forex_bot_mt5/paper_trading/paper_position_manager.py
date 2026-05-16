"""Paper position persistence and lifecycle management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable

from agi_style_forex_bot_mt5.contracts import MarketSnapshot, TradeSignal, RiskDecision
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from .paper_fill_model import PaperFillModel
from .paper_trade import PaperTrade


class PaperPositionManager:
    """Open, reload and update paper trades stored in SQLite."""

    def __init__(
        self,
        *,
        database: TelemetryDatabase,
        fill_model: PaperFillModel | None = None,
        break_even_trigger_r: float = 0.6,
        trailing_start_r: float = 0.8,
        trailing_distance_r: float = 0.5,
        time_stop_seconds: int | None = None,
    ) -> None:
        self.database = database
        self.fill_model = fill_model or PaperFillModel()
        self.break_even_trigger_r = break_even_trigger_r
        self.trailing_start_r = trailing_start_r
        self.trailing_distance_r = trailing_distance_r
        self.time_stop_seconds = time_stop_seconds

    def load_open_trades(self) -> tuple[PaperTrade, ...]:
        trades = []
        for row in self.database.fetch_open_paper_trades():
            trades.append(PaperTrade.from_json(row["payload_json"]))
        return tuple(trades)

    def load_all_trades(self) -> tuple[PaperTrade, ...]:
        trades = []
        for row in self.database.fetch_paper_trades():
            trades.append(PaperTrade.from_json(row["payload_json"]))
        return tuple(trades)

    def open_trade(
        self,
        *,
        signal: TradeSignal,
        risk_decision: RiskDecision,
        snapshot: MarketSnapshot,
        broker_symbol: str,
        score: float,
        reasons: Iterable[str],
        strategy_name: str,
        strategy_version: str,
        regime: str,
        session: str,
    ) -> PaperTrade:
        key = f"paper_trade:{signal.signal_id}:{signal.symbol}:{signal.direction.value}"
        existing = self.database.fetch_paper_trade_by_idempotency(key)
        if existing is not None:
            return PaperTrade.from_json(existing["payload_json"])
        entry = self.fill_model.entry_price(direction=signal.direction.value, snapshot=snapshot)
        risk_amount = float(risk_decision.risk_amount_account_currency or 0.0)
        effective_risk_pct = float(risk_decision.checks.get("effective_risk_pct") or signal.risk_pct or 0.0)
        trade = PaperTrade(
            paper_trade_id=PaperTrade.new_id(),
            signal_id=signal.signal_id,
            idempotency_key=key,
            symbol=signal.symbol,
            broker_symbol=broker_symbol,
            direction=signal.direction.value,
            entry_time_utc=snapshot.timestamp_utc.astimezone(timezone.utc).isoformat(),
            entry_price=round(entry, snapshot.digits),
            sl_price=signal.sl_price,
            tp_price=signal.tp_price,
            lot=risk_decision.approved_lot,
            risk_pct=effective_risk_pct,
            risk_amount=risk_amount,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            regime=regime,
            session=session,
            score=float(score),
            reasons=tuple(reasons),
            spread_at_entry=snapshot.spread_points,
            slippage_assumed_points=self.fill_model.slippage_points,
            commission_assumed=self.fill_model.commission(risk_decision.approved_lot),
        )
        inserted = self.database.insert_paper_trade(trade.to_dict())
        if inserted:
            self.database.insert_paper_trade_event(trade.paper_trade_id, "PAPER_TRADE_OPENED", trade.to_dict())
        return trade

    def update_with_snapshot(self, trade: PaperTrade, snapshot: MarketSnapshot) -> PaperTrade:
        if trade.status != "OPEN":
            return trade
        now = snapshot.timestamp_utc.astimezone(timezone.utc)
        risk_distance = abs(trade.entry_price - trade.sl_price)
        if risk_distance <= 0:
            raise ValueError("paper trade has invalid risk distance")
        favorable, adverse = self._excursions(trade, snapshot)
        mae = min(trade.mae, adverse)
        mfe = max(trade.mfe, favorable)
        updated = trade.replace(mae=mae, mfe=mfe)
        new_sl = self._managed_stop(updated, risk_distance)
        if new_sl != updated.sl_price:
            updated = updated.replace(sl_price=new_sl)
            self.database.update_paper_trade(updated.to_dict())
            self.database.insert_paper_trade_event(updated.paper_trade_id, "PAPER_TRADE_MODIFIED", updated.to_dict())
        close_reason, base_exit = self._close_condition(updated, snapshot)
        if close_reason is None and self.time_stop_seconds is not None:
            opened = datetime.fromisoformat(updated.entry_time_utc)
            if (now - opened).total_seconds() >= self.time_stop_seconds:
                close_reason = "TIME_STOP"
                base_exit = snapshot.bid if updated.direction == "BUY" else snapshot.ask
        if close_reason is None:
            self.database.update_paper_trade(updated.to_dict())
            return updated
        return self.close_trade(updated, snapshot, close_reason, base_exit)

    def close_trade(
        self,
        trade: PaperTrade,
        snapshot: MarketSnapshot,
        reason: str,
        base_exit_price: float,
    ) -> PaperTrade:
        exit_price = self.fill_model.exit_price(direction=trade.direction, snapshot=snapshot, base_price=base_exit_price)
        profit = self._profit(trade, exit_price, snapshot)
        planned_risk = max(trade.risk_amount, abs(trade.entry_price - trade.sl_price) / snapshot.point * trade.lot)
        r_multiple = profit / planned_risk if planned_risk > 0 else 0.0
        closed = trade.replace(
            status="CLOSED",
            exit_time_utc=snapshot.timestamp_utc.astimezone(timezone.utc).isoformat(),
            exit_price=round(exit_price, snapshot.digits),
            exit_reason=reason,
            profit=profit,
            r_multiple=r_multiple,
            spread_at_exit=snapshot.spread_points,
        )
        self.database.update_paper_trade(closed.to_dict())
        self.database.insert_paper_trade_event(closed.paper_trade_id, "PAPER_TRADE_CLOSED", closed.to_dict())
        return closed

    def _managed_stop(self, trade: PaperTrade, risk_distance: float) -> float:
        stop = trade.sl_price
        if trade.mfe >= self.break_even_trigger_r * risk_distance:
            stop = max(stop, trade.entry_price) if trade.direction == "BUY" else min(stop, trade.entry_price)
        if trade.mfe >= self.trailing_start_r * risk_distance:
            trail_distance = self.trailing_distance_r * risk_distance
            if trade.direction == "BUY":
                stop = max(stop, trade.entry_price + trade.mfe - trail_distance)
            else:
                stop = min(stop, trade.entry_price - trade.mfe + trail_distance)
        return stop

    def _close_condition(self, trade: PaperTrade, snapshot: MarketSnapshot) -> tuple[str | None, float]:
        if trade.direction == "BUY":
            if snapshot.bid <= trade.sl_price:
                return ("BREAK_EVEN" if trade.sl_price >= trade.entry_price else "SL"), trade.sl_price
            if snapshot.bid >= trade.tp_price:
                return "TP", trade.tp_price
        else:
            if snapshot.ask >= trade.sl_price:
                return ("BREAK_EVEN" if trade.sl_price <= trade.entry_price else "SL"), trade.sl_price
            if snapshot.ask <= trade.tp_price:
                return "TP", trade.tp_price
        return None, 0.0

    def _excursions(self, trade: PaperTrade, snapshot: MarketSnapshot) -> tuple[float, float]:
        if trade.direction == "BUY":
            favorable = snapshot.bid - trade.entry_price
            adverse = snapshot.bid - trade.entry_price
        else:
            favorable = trade.entry_price - snapshot.ask
            adverse = trade.entry_price - snapshot.ask
        return favorable, adverse

    def _profit(self, trade: PaperTrade, exit_price: float, snapshot: MarketSnapshot) -> float:
        move = exit_price - trade.entry_price
        if trade.direction == "SELL":
            move *= -1.0
        return (move / snapshot.tick_size) * snapshot.tick_value * trade.lot - trade.commission_assumed
