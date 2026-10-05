"""Paper position persistence and lifecycle management."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from agi_style_forex_bot_mt5.contracts import Environment, Event, MarketSnapshot, TradeSignal, RiskDecision, Severity
from agi_style_forex_bot_mt5.execution_simulation.fill_model import FillResult
from agi_style_forex_bot_mt5.micro_v2_pre_relaunch_safety_pack import PaperTradeGuardInput, validate_paper_trade_creation
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase
from agi_style_forex_bot_mt5.risk.position_sizer import normalize_lot_down, price_risk_per_lot

from .paper_fill_model import PaperFillModel
from .paper_pnl_engine import calculate_scaled_paper_pnl
from .paper_trade import PaperTrade

APPROVED_LOT_BASIS = "APPROVED_LOT_UNSCALED_V1"


class PaperAuditError(ValueError):
    """A required paper lifecycle audit could not be durably confirmed."""
    code = "PAPER_AUDIT_FAILED"


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
        profile_config: str | None = None,
    ) -> None:
        self.database = database
        self.fill_model = fill_model or PaperFillModel()
        self.break_even_trigger_r = break_even_trigger_r
        self.trailing_start_r = trailing_start_r
        self.trailing_distance_r = trailing_distance_r
        self.time_stop_seconds = time_stop_seconds
        self.profile_config = profile_config

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
        if risk_decision.accepted is not True or risk_decision.signal_id != signal.signal_id:
            raise ValueError("paper entry requires an accepted matching risk decision")
        for value in (risk_decision.approved_lot, risk_decision.risk_amount_account_currency):
            if not _finite(value) or value <= 0:
                raise ValueError("paper entry requires positive finite lot and risk")
        snapshot.validate()
        for value in (snapshot.bid, snapshot.ask, snapshot.point, snapshot.tick_value, snapshot.tick_size,
                      snapshot.volume_min, snapshot.volume_max, snapshot.volume_step):
            if not _finite(value) or value <= 0:
                raise ValueError("paper entry requires finite positive broker metadata")
        volume = risk_decision.approved_lot
        if not snapshot.volume_min <= volume <= snapshot.volume_max or not math.isclose(normalize_lot_down(volume, snapshot), volume, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError("paper entry lot violates broker limits")
        prices = (snapshot.bid, snapshot.ask, signal.sl_price, signal.tp_price)
        if signal.entry_price is not None:
            prices += (signal.entry_price,)
        if not all(_on_tick_grid(price, snapshot.tick_size) for price in prices):
            raise ValueError("paper entry/protection price violates broker tick grid")
        intent_fingerprint = self._intent_fingerprint(signal, risk_decision, strategy_name, strategy_version)
        key = f"paper_trade:{signal.signal_id}:{signal.symbol}"
        existing = self._existing_intent(signal, strategy_name, strategy_version, intent_fingerprint)
        if existing is not None:
            return existing
        for value in (self.fill_model.slippage_points, self.fill_model.commission_per_lot_round_turn):
            if not _finite(value) or value < 0:
                raise ValueError("paper fill cost assumptions must be finite and non-negative")
        entry_result = self.fill_model.entry_result(direction=signal.direction.value, snapshot=snapshot, lot=risk_decision.approved_lot)
        if not entry_result.accepted or entry_result.fill_price is None:
            raise ValueError(f"paper fill rejected: {entry_result.reject_reason or entry_result.reject_code}")
        for value in (entry_result.fill_price, entry_result.assumed_slippage_points, entry_result.commission):
            if not _finite(value) or value < 0:
                raise ValueError("paper fill returned invalid price, slippage or commission")
        if not _on_tick_grid(entry_result.fill_price, snapshot.tick_size):
            raise ValueError("paper entry/protection price violates broker tick grid")
        entry = entry_result.fill_price
        guard = validate_paper_trade_creation(
            PaperTradeGuardInput(
                entry_price=round(entry, snapshot.digits),
                sl_price=signal.sl_price,
                tp_price=signal.tp_price,
                side=signal.direction.value,
                digits=snapshot.digits,
                metadata=dict(signal.metadata),
            )
        )
        if not guard.get("paper_trade_creation_allowed"):
            self._record_creation_rejection(signal=signal, snapshot=snapshot, guard=guard, broker_symbol=broker_symbol)
            raise ValueError(str(guard.get("rejection_reason") or "PAPER_TRADE_REJECTED_INVALID_SETUP"))
        signal.validate_against_snapshot(snapshot)
        entry_result, final_lot, risk_amount, effective_risk_pct, reconciliation = self._reconcile_fill_risk(
            signal=signal, risk_decision=risk_decision, snapshot=snapshot, entry_result=entry_result,
        )
        entry = entry_result.fill_price
        self._persist_reconciliation(signal, snapshot, reconciliation)
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
            lot=final_lot,
            risk_pct=effective_risk_pct,
            risk_amount=risk_amount,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            regime=regime,
            session=session,
            score=float(score),
            reasons=tuple(reasons),
            spread_at_entry=snapshot.spread_points,
            slippage_assumed_points=entry_result.assumed_slippage_points,
            commission_assumed=entry_result.commission,
            metadata={
                "pnl_basis": APPROVED_LOT_BASIS,
                "initial_sl_price": signal.sl_price,
                "initial_risk_distance": abs(round(entry, snapshot.digits) - signal.sl_price),
                "initial_risk_amount": risk_amount,
                "entry_intent_fingerprint": intent_fingerprint,
                "fill_risk_reconciliation": reconciliation,
                "entry_risk_adjustment": dict(risk_decision.checks),
                "execution_simulation_version": str((entry_result.metadata or {}).get("execution_simulation_version", "")),
                "fill_quality": entry_result.fill_quality,
                "entry_fill": entry_result.to_dict(),
                "spread_model_used": (entry_result.metadata or {}).get("spread_model_used", {}),
                "slippage_model_used": (entry_result.metadata or {}).get("slippage_model_used", {}),
                "commission_model_used": (entry_result.metadata or {}).get("commission_model_used", {}),
                "latency_assumption": (entry_result.metadata or {}).get("latency_assumption", {}),
                "ambiguity_flags": (entry_result.metadata or {}).get("ambiguity_flags", ()),
            },
        )
        inserted = self.database.insert_paper_trade(trade.to_dict())
        if inserted:
            self.database.insert_paper_trade_event(trade.paper_trade_id, "PAPER_TRADE_OPENED", trade.to_dict(), timestamp_utc=snapshot.timestamp_utc)
            return trade
        existing = self._existing_intent(signal, strategy_name, strategy_version, intent_fingerprint)
        if existing is None:
            raise ValueError("paper trade persistence was not confirmed")
        return existing

    def _intent_fingerprint(self, signal: TradeSignal, risk_decision: RiskDecision, strategy_name: str, strategy_version: str) -> str:
        """Bind retries to the original setup and configuration content."""
        profile_digest = None
        if self.profile_config:
            try:
                profile_digest = sha256(Path(self.profile_config).read_bytes()).hexdigest()
            except OSError as exc:
                raise ValueError("paper entry profile configuration cannot be verified") from exc
        body = {
            "symbol": signal.symbol, "timeframe": signal.timeframe, "direction": signal.direction.value,
            "entry_type": signal.entry_type.value, "entry_price": signal.entry_price,
            "sl": signal.sl_price, "tp": signal.tp_price, "risk_pct": signal.risk_pct,
            "approved_lot": risk_decision.approved_lot, "risk_budget": risk_decision.risk_amount_account_currency,
            "strategy_name": strategy_name, "strategy_version": strategy_version,
            "signal_metadata": dict(signal.metadata), "profile_digest": profile_digest,
            "slippage_points": self.fill_model.slippage_points,
            "commission_per_lot_round_turn": self.fill_model.commission_per_lot_round_turn,
            "max_spread_points": self.fill_model.max_spread_points,
            "max_tick_age_seconds": self.fill_model.max_tick_age_seconds,
            "break_even_trigger_r": self.break_even_trigger_r, "trailing_start_r": self.trailing_start_r,
            "trailing_distance_r": self.trailing_distance_r, "time_stop_seconds": self.time_stop_seconds,
        }
        try:
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("paper entry intent must contain finite serializable values") from exc
        return sha256(encoded.encode("utf-8")).hexdigest()

    def _existing_intent(self, signal: TradeSignal, strategy_name: str, strategy_version: str, fingerprint: str) -> PaperTrade | None:
        matches = []
        for row in self.database.fetch_paper_trades():
            existing = PaperTrade.from_json(row["payload_json"])
            if existing.signal_id == signal.signal_id:
                matches.append(existing)
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("paper signal identity has multiple existing trades")
        existing = matches[0]
        same_geometry = (
            existing.symbol == signal.symbol and existing.direction == signal.direction.value
            and existing.metadata.get("initial_sl_price", existing.sl_price) == signal.sl_price
            and existing.tp_price == signal.tp_price and existing.strategy_name == strategy_name
            and existing.strategy_version == strategy_version
        )
        if not same_geometry or existing.metadata.get("entry_intent_fingerprint") != fingerprint:
            raise ValueError("paper signal identity conflicts with existing entry intent or unverifiable legacy intent")
        return existing

    def _reconcile_fill_risk(
        self, *, signal: TradeSignal, risk_decision: RiskDecision,
        snapshot: MarketSnapshot, entry_result: FillResult,
    ) -> tuple[FillResult, float, float, float, dict[str, Any]]:
        """Reduce approved volume to reserve the modeled loss including costs."""
        budget = float(risk_decision.risk_amount_account_currency)
        price_risk = price_risk_per_lot(round(entry_result.fill_price, snapshot.digits), signal.sl_price, snapshot)
        exit_reserve = self.fill_model.slippage_points * snapshot.point / snapshot.tick_size * snapshot.tick_value
        stop_result = self.fill_model.exit_result(direction=signal.direction.value, snapshot=snapshot, lot=0.0, base_price=signal.sl_price)
        modeled_stop_fill = stop_result.fill_price
        if stop_result.accepted is not True or not _on_tick_grid(modeled_stop_fill, snapshot.tick_size):
            raise ValueError("paper stop fill risk cannot be reconciled")
        if not _finite(stop_result.assumed_slippage_points) or stop_result.assumed_slippage_points < 0:
            raise ValueError("paper stop slippage cannot be reconciled")
        # Ask the same pure simulator used at close; rounding to digits or the
        # broker tick grid may enlarge the realized loss beyond nominal slip.
        if modeled_stop_fill != signal.sl_price:
            exit_reserve = max(exit_reserve, price_risk_per_lot(signal.sl_price, modeled_stop_fill, snapshot))
        commission_rate = self.fill_model.commission_per_lot_round_turn
        risk_per_lot = price_risk + exit_reserve + commission_rate
        if not _finite(risk_per_lot) or risk_per_lot <= 0:
            raise ValueError("paper post-fill risk cannot be calculated")
        lot = normalize_lot_down(min(risk_decision.approved_lot, budget / risk_per_lot), snapshot)
        if lot < snapshot.volume_min or lot <= 0:
            self._persist_reconciliation(signal, snapshot, {"accepted": False, "reason": "POST_FILL_LOT_BELOW_MINIMUM",
                                         "approved_lot": risk_decision.approved_lot, "approved_risk_budget": budget,
                                         "risk_per_lot_with_costs": risk_per_lot})
            raise ValueError("post-fill risk budget cannot fit broker minimum lot")
        final_fill = self.fill_model.entry_result(direction=signal.direction.value, snapshot=snapshot, lot=lot)
        if final_fill.accepted is not True or final_fill.fill_price != entry_result.fill_price:
            raise ValueError("paper fill changed during risk reconciliation")
        expected_commission = commission_rate * lot
        if not _finite(final_fill.commission) or final_fill.commission < 0 or not math.isclose(final_fill.commission, expected_commission, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("paper fill commission cannot be reconciled")
        if not _finite(final_fill.assumed_slippage_points) or final_fill.assumed_slippage_points < 0:
            raise ValueError("paper fill slippage cannot be reconciled")
        amount = (price_risk + exit_reserve) * lot + final_fill.commission
        if not _finite(amount) or amount <= 0 or amount > budget + 1e-9 or lot > risk_decision.approved_lot:
            raise ValueError("post-fill risk exceeds approved budget")
        account_check = risk_decision.checks.get("account_equity")
        if isinstance(account_check, Mapping) and account_check.get("status") == "passed":
            equity = account_check.get("equity")
            if not _finite(equity) or equity <= 0:
                raise ValueError("paper risk equity is invalid")
            risk_pct = amount / equity * 100.0
        else:
            approved_pct = risk_decision.checks.get("effective_risk_pct", signal.risk_pct)
            if not _finite(approved_pct) or approved_pct <= 0:
                raise ValueError("paper approved risk percentage is unavailable")
            risk_pct = approved_pct * amount / budget
        reconciliation = {
            "accepted": True, "reason": "POST_FILL_RISK_RECONCILED", "version": "paper_fill_risk_v1",
            "approved_lot": risk_decision.approved_lot, "approved_risk_budget": budget,
            "final_lot": lot, "lot_reduced": lot < risk_decision.approved_lot,
            "fill_price": final_fill.fill_price, "sl_price": signal.sl_price,
            "modeled_stop_fill": modeled_stop_fill,
            "price_risk_per_lot": price_risk, "exit_slippage_reserve_per_lot": exit_reserve,
            "commission_per_lot_round_turn": commission_rate, "commission_final": final_fill.commission,
            "final_risk_amount": amount, "final_risk_pct": risk_pct,
            "risk_scope": "ENTRY_TO_INITIAL_SL_PLUS_FIXED_EXIT_SLIPPAGE_AND_ROUND_TURN_COMMISSION",
            "gap_risk_bounded": False,
        }
        return final_fill, lot, amount, risk_pct, reconciliation

    def _persist_reconciliation(self, signal: TradeSignal, snapshot: MarketSnapshot, reconciliation: Mapping[str, Any]) -> None:
        """Require a durable, readable audit record before persisting a position."""
        payload = {"signal_id": signal.signal_id, "symbol": signal.symbol, **reconciliation}
        digest = sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
        payload["reconciliation_fingerprint"] = digest
        key = f"paper_fill_risk:{digest}"
        event_type = "PAPER_FILL_RISK_RECONCILED" if reconciliation["accepted"] else "PAPER_FILL_RISK_REJECTED"
        try:
            self.database.insert_event(Event(
                event_id=f"evt_{uuid4().hex}", schema_version="1.0", idempotency_key=key, event_type=event_type,
                correlation_id=signal.signal_id, signal_id=signal.signal_id, symbol=signal.symbol,
                severity=Severity.INFO if reconciliation["accepted"] else Severity.WARNING, module="paper_trading",
                message=reconciliation["reason"], payload=payload,
                timestamp_utc=snapshot.timestamp_utc.astimezone(timezone.utc),
                environment=Environment.DEMO, run_id="paper_fill_risk_reconciliation",
            ))
            persisted = self.database.fetch_by_idempotency_key("events", key)
            if persisted is None or persisted["event_type"] != event_type or json.loads(persisted["payload_json"]).get("reconciliation_fingerprint") != digest:
                raise ValueError("paper risk reconciliation audit was not persisted")
        except Exception as exc:
            raise PaperAuditError("paper risk reconciliation audit failed") from exc

    def _record_creation_rejection(self, *, signal: TradeSignal, snapshot: MarketSnapshot, guard: dict[str, object], broker_symbol: str) -> None:
        payload = {
            **guard,
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "broker_symbol": broker_symbol,
            "entry_price": guard.get("entry_price", signal.entry_price),
            "sl_price": signal.sl_price,
            "tp_price": signal.tp_price,
            "timestamp_utc": snapshot.timestamp_utc.astimezone(timezone.utc).isoformat(),
        }
        self.database.insert_event(
            {
                "event_id": f"evt_{uuid4().hex}",
                "event_type": "PAPER_TRADE_CREATION_REJECTED",
                "severity": "WARNING",
                "module": "paper_trading",
                "symbol": signal.symbol,
                "signal_id": signal.signal_id,
                "message": str(guard.get("rejection_reason") or "paper_trade_creation_rejected"),
                "payload_json": json.dumps(payload, sort_keys=True),
                "timestamp_utc": snapshot.timestamp_utc.astimezone(timezone.utc).isoformat(),
                "environment": "DEMO",
                "run_id": "paper_trade_creation_guard",
                "idempotency_key": f"paper_trade_creation_rejected:{signal.signal_id}:{guard.get('rejection_reason', '')}",
            }
        )

    def update_with_snapshot(self, trade: PaperTrade, snapshot: MarketSnapshot) -> PaperTrade:
        if trade.status != "OPEN":
            return trade
        now = snapshot.timestamp_utc.astimezone(timezone.utc)
        risk_distance = float(trade.metadata.get("initial_risk_distance", abs(trade.entry_price - trade.sl_price)))
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
            self.database.insert_paper_trade_event(updated.paper_trade_id, "PAPER_TRADE_MODIFIED", updated.to_dict(), timestamp_utc=snapshot.timestamp_utc)
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
        exit_result = self.fill_model.exit_result(direction=trade.direction, snapshot=snapshot, lot=trade.lot, base_price=base_exit_price)
        if not exit_result.accepted or exit_result.fill_price is None:
            raise ValueError(f"paper exit fill rejected: {exit_result.reject_reason or exit_result.reject_code}")
        exit_price = exit_result.fill_price
        raw_profit = self._profit(trade, exit_price, snapshot)
        if trade.metadata.get("pnl_basis") == APPROVED_LOT_BASIS:
            # Lot is already adjusted by the decision pipeline. Multiplying PnL
            # again understates both profits and drawdown.
            pnl = {"scaled_paper_pnl": raw_profit, "paper_risk_multiplier": 1.0,
                   "risk_multiplier": 1.0, "pnl_formula_version": "paper_pnl_approved_lot_v1",
                   "multiplier_applied": False, "pnl_scaling_status": APPROVED_LOT_BASIS}
        else:
            # Legacy evidence is not silently restated. Decision-state validation
            # blocks new entries into a book with unreviewed legacy accounting.
            pnl = calculate_scaled_paper_pnl(
                {**trade.to_dict(), "exit_price": exit_price, "tick_size": snapshot.tick_size, "tick_value": snapshot.tick_value},
                profile_config=self.profile_config,
                symbol_contract={"tick_size": snapshot.tick_size, "tick_value": snapshot.tick_value, "point": snapshot.point},
            )
        profit = float(pnl["scaled_paper_pnl"])
        planned_risk = float(trade.metadata.get("initial_risk_amount", trade.risk_amount))
        r_multiple = profit / planned_risk if planned_risk > 0 else 0.0
        closed = trade.replace(
            status="CLOSED",
            exit_time_utc=snapshot.timestamp_utc.astimezone(timezone.utc).isoformat(),
            exit_price=round(exit_price, snapshot.digits),
            exit_reason=reason,
            profit=profit,
            raw_pnl=raw_profit,
            scaled_paper_pnl=profit,
            paper_risk_multiplier=float(pnl["paper_risk_multiplier"]),
            risk_multiplier=float(pnl["risk_multiplier"]),
            pnl_formula_version=str(pnl["pnl_formula_version"]),
            multiplier_applied=bool(pnl["multiplier_applied"]),
            pnl_scaling_status=str(pnl["pnl_scaling_status"]),
            r_multiple=r_multiple,
            spread_at_exit=snapshot.spread_points,
            metadata={
                **dict(trade.metadata),
                "exit_fill": exit_result.to_dict(),
                "raw_pnl": raw_profit,
                "scaled_paper_pnl": profit,
                "paper_risk_multiplier": float(pnl["paper_risk_multiplier"]),
                "risk_multiplier": float(pnl["risk_multiplier"]),
                "pnl_formula_version": str(pnl["pnl_formula_version"]),
                "multiplier_applied": bool(pnl["multiplier_applied"]),
                "pnl_scaling_status": str(pnl["pnl_scaling_status"]),
                "pnl_warnings": list(pnl.get("warnings", [])),
                "fill_quality": _worst_quality(str(trade.metadata.get("fill_quality", "GOOD")), exit_result.fill_quality),
            },
        )
        self.database.update_paper_trade(closed.to_dict())
        self.database.insert_paper_trade_event(closed.paper_trade_id, "PAPER_TRADE_CLOSED", closed.to_dict(), timestamp_utc=snapshot.timestamp_utc)
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
                return ("BREAK_EVEN" if trade.sl_price >= trade.entry_price else "SL"), min(trade.sl_price, snapshot.bid)
            if snapshot.bid >= trade.tp_price:
                return "TP", trade.tp_price
        else:
            if snapshot.ask >= trade.sl_price:
                return ("BREAK_EVEN" if trade.sl_price <= trade.entry_price else "SL"), max(trade.sl_price, snapshot.ask)
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


def _worst_quality(left: str, right: str) -> str:
    order = {"GOOD": 0, "ACCEPTABLE": 1, "POOR": 2, "REJECTED": 3}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _on_tick_grid(price: float | None, tick_size: float) -> bool:
    if not _finite(price) or price <= 0:
        return False
    try:
        return Decimal(str(price)) % Decimal(str(tick_size)) == 0
    except (InvalidOperation, ZeroDivisionError):
        return False
