"""Persistent paper capital and complete risk inputs; no broker-side actions.

One forward-shadow writer owns a telemetry database. Existing paper history
without a capital baseline or explicit PnL provenance requires reconciliation;
it is never adopted silently using the currently displayed broker balance.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Protocol

from ..contracts import AccountState, Direction, MarketSnapshot, PositionState
from ..core.operational_state.errors import PaperStateError
from ..core.price_grid import is_price_on_tick_grid
from ..risk.emergency_kill_switch import KillSwitchState
from ..risk.risk_engine import RiskRuntimeState
from ..risk.position_sizer import normalize_lot_down
from .paper_trade import PaperTrade


PAPER_DECISION_STATE_KEY = "paper_decision_state_v1"
PAPER_PNL_ACCOUNTING_BASIS = "APPROVED_LOT_UNSCALED_V1"


class PaperStateStore(Protocol):
    def get_operational_state(self) -> dict[str, Any]: ...

    def update_operational_state(self, updates: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PaperDecisionState:
    account: AccountState
    risk_state: RiskRuntimeState
    initial_balance: float
    realized_pnl: float
    floating_pnl: float
    operational_day: str
    portfolio_open_trades: tuple[Mapping[str, Any], ...] = ()


def build_paper_decision_state(
    *,
    database: PaperStateStore,
    trades: Iterable[PaperTrade],
    snapshots_by_symbol: Mapping[str, MarketSnapshot],
    account_template: AccountState,
    now_utc: datetime,
    max_snapshot_age_seconds: float = 5,
    audit_confirmed: bool = False,
    max_daily_drawdown_pct: float = 3.0,
    _capture_daily_boundary: bool = False,
) -> PaperDecisionState:
    """Build complete account/risk state or raise a structured PaperStateError.

    Bootstrap is allowed only with zero existing trades. Daily references are
    persisted before returning. Missing overnight equity cannot be inferred
    from today's prices, so an absent reference with a midnight-spanning trade
    blocks the state. ``audit_confirmed`` defaults false and is never fabricated.
    """

    now = _utc(now_utc, "now_utc")
    if type(_capture_daily_boundary) is not bool or (_capture_daily_boundary and now.time() != datetime.min.time()):
        _fail("daily boundary capture requires exactly midnight UTC", "DAILY_DRAWDOWN_REFERENCE_MISSING")
    max_age = _number(max_snapshot_age_seconds, "max_snapshot_age_seconds", positive=True)
    daily_limit = _number(max_daily_drawdown_pct, "max_daily_drawdown_pct", positive=True)
    if daily_limit > 3.0 or max_age > 5.0 or type(audit_confirmed) is not bool:
        _fail("invalid paper decision safety configuration")
    currency = account_template.currency
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        _fail("paper denomination currency is unknown")
    currency = currency.upper()
    history = tuple(trades)
    previous = _read_state(database)
    if previous is None:
        if history:
            _fail("paper capital baseline is missing for existing trades", "PAPER_CAPITAL_REFERENCE_MISSING")
        state: dict[str, Any] = {
            "schema_version": "1.0", "initial_balance": _number(account_template.balance, "initial_balance", positive=True),
            "currency": currency, "created_at_utc": now.isoformat(),
            "last_observed_at_utc": now.isoformat(), "daily_references": {}, "known_trades": {},
        }
    else:
        state = _validate_state(copy.deepcopy(previous), currency, now)
    initial_balance = state["initial_balance"]
    day = now.date().isoformat()
    day_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
    known: dict[str, Any] = {}
    positions: list[PositionState] = []
    risks: dict[int, float] = {}
    used_snapshots: dict[str, MarketSnapshot] = {}
    marked_trades: list[tuple[PaperTrade, float]] = []
    realized_values: list[float] = []
    floating_values: list[float] = []
    closed: list[tuple[datetime, float]] = []
    balance_before_day_values: list[float] = []
    spans_midnight = False
    for trade in history:
        if not isinstance(trade, PaperTrade):
            _fail("paper history contains an invalid trade")
        if not isinstance(trade.paper_trade_id, str) or not trade.paper_trade_id:
            _fail("paper trade identity is missing")
        identity = "p_" + hashlib.sha256(trade.paper_trade_id.encode("utf-8")).hexdigest()
        if identity in known:
            _fail("duplicate paper trade identity")
        if trade.metadata.get("pnl_basis") != PAPER_PNL_ACCOUNTING_BASIS:
            _fail("legacy paper PnL accounting requires explicit reconciliation", "PAPER_PNL_PROVENANCE_UNVERIFIED")
        if trade.multiplier_applied is not False:
            _fail("paper lot accounting was additionally scaled", "PAPER_PNL_PROVENANCE_UNVERIFIED")
        for field in ("paper_risk_multiplier", "risk_multiplier"):
            if _number(getattr(trade, field), field, positive=True) != 1.0:
                _fail("paper lot accounting conflicts with an additional PnL multiplier", "PAPER_PNL_PROVENANCE_UNVERIFIED")
            if field in trade.metadata and _number(trade.metadata[field], field, positive=True) != 1.0:
                _fail("paper metadata contains an additional PnL multiplier", "PAPER_PNL_PROVENANCE_UNVERIFIED")
        opened = _utc(trade.entry_time_utc, "entry_time_utc")
        if opened > now:
            _fail("paper trade entry is in the future")
        if opened < _utc(state["created_at_utc"], "created_at_utc") - timedelta(seconds=max_age):
            _fail("paper trade predates the persisted capital baseline")
        entry = _number(trade.entry_price, "entry_price", positive=True)
        lot = _number(trade.lot, "lot", positive=True)
        sl = _number(trade.sl_price, "sl_price", positive=True)
        tp = _number(trade.tp_price, "tp_price", positive=True)
        commission = _number(trade.commission_assumed, "commission_assumed", nonnegative=True)
        initial_risk = _number(trade.risk_amount, "risk_amount", positive=True)
        if trade.direction not in ("BUY", "SELL") or trade.status not in ("OPEN", "CLOSED"):
            _fail("paper trade direction or status is invalid")
        if not isinstance(trade.symbol, str) or not trade.symbol:
            _fail("paper trade symbol is missing")
        if not isinstance(trade.broker_symbol, str) or not trade.broker_symbol:
            _fail("paper broker symbol is missing")
        signature = {"entry_time_utc": opened.isoformat(), "symbol": trade.symbol, "broker_symbol": trade.broker_symbol, "direction": trade.direction, "entry_price": entry, "lot": lot, "risk_amount": initial_risk, "commission_assumed": commission}
        prior_trade = state["known_trades"].get(identity)
        if prior_trade is not None and any(prior_trade.get(key) != value for key, value in signature.items()):
            _fail("persisted paper trade identity or economic terms changed")
        if trade.status == "CLOSED":
            exited = _utc(trade.exit_time_utc, "exit_time_utc")
            if not opened <= exited <= now:
                _fail("paper trade exit chronology is invalid")
            _number(trade.exit_price, "exit_price", positive=True)
            if trade.pnl_formula_version != "paper_pnl_approved_lot_v1":
                _fail("closed paper PnL formula version is unverified", "PAPER_PNL_PROVENANCE_UNVERIFIED")
            pnl = _number(trade.profit, "profit")
            if any(not math.isclose(_number(getattr(trade, field), field), pnl, rel_tol=1e-10, abs_tol=1e-8) for field in ("raw_pnl", "scaled_paper_pnl")):
                _fail("closed paper PnL fields disagree with approved-lot accounting", "PAPER_PNL_PROVENANCE_UNVERIFIED")
            signature.update(status="CLOSED", exit_time_utc=exited.isoformat(), profit=pnl)
            realized_values.append(pnl)
            closed.append((exited, pnl))
            if exited < day_start:
                balance_before_day_values.append(pnl)
            if opened < day_start <= exited:
                spans_midnight = True
        else:
            if trade.exit_time_utc is not None or trade.exit_price is not None:
                _fail("open paper trade contains a closing record")
            snapshot = snapshots_by_symbol.get(trade.symbol)
            _validate_snapshot(snapshot, trade.symbol, now, max_age)
            assert snapshot is not None
            if not all(is_price_on_tick_grid(price, snapshot.tick_size) for price in (entry, sl, tp)):
                _fail("paper position price/protection violates observed broker tick grid", "PAPER_PROTECTION_GRID_INVALID")
            if not snapshot.volume_min <= lot <= snapshot.volume_max or not math.isclose(lot, normalize_lot_down(lot, snapshot), rel_tol=0, abs_tol=1e-8):
                _fail("paper position volume is incompatible with observed instrument metadata")
            mark = snapshot.bid if trade.direction == "BUY" else snapshot.ask
            if not (sl < mark < tp if trade.direction == "BUY" else tp < mark < sl):
                _fail("paper position has reached an exit or has invalid protection; reconcile its lifecycle first")
            signed_move = mark - entry if trade.direction == "BUY" else entry - mark
            pnl = _number(signed_move / snapshot.tick_size * snapshot.tick_value * lot - commission, "floating_pnl")
            distance_to_stop = mark - sl if trade.direction == "BUY" else sl - mark
            # Retaining at least the original approved risk avoids understating
            # exposure after stop modifications or imperfect legacy metadata.
            risk = max(initial_risk, _number(distance_to_stop / snapshot.tick_size * snapshot.tick_value * lot, "open_risk", positive=True))
            ticket = int(identity[2:17], 16) or 1
            if ticket in risks:
                _fail("paper position risk identity collision")
            positions.append(PositionState(ticket=ticket, symbol=trade.symbol, direction=Direction(trade.direction), volume=lot, entry_price=entry, sl_price=sl, tp_price=tp, magic_number=0, floating_profit=pnl))
            risks[ticket] = risk
            marked_trades.append((trade, risk))
            used_snapshots[trade.symbol] = snapshot
            floating_values.append(pnl)
            signature["status"] = "OPEN"
            spans_midnight = spans_midnight or opened < day_start
        if prior_trade is not None and prior_trade.get("status") == "CLOSED" and prior_trade != signature:
            _fail("closed paper history changed or reopened")
        known[identity] = signature
    if not set(state["known_trades"]).issubset(known):
        _fail("previously observed paper trades are missing from the supplied history")
    realized = _number(math.fsum(realized_values), "realized_pnl")
    floating = _number(math.fsum(floating_values), "floating_pnl")
    balance = _number(initial_balance + realized, "paper_balance")
    equity = _number(balance + floating, "paper_equity")
    references = state["daily_references"]
    if day not in references:
        if spans_midnight:
            if not _capture_daily_boundary:
                _fail("daily equity reference is missing for midnight-spanning paper exposure", "DAILY_DRAWDOWN_REFERENCE_MISSING")
            for trade in history:
                opened = _utc(trade.entry_time_utc, "entry_time_utc")
                crossed = opened < day_start and (trade.status == "OPEN" or _utc(trade.exit_time_utc, "exit_time_utc") == day_start)
                if crossed:
                    quote = snapshots_by_symbol.get(trade.symbol)
                    _validate_snapshot(quote, trade.symbol, now, max_age)
                    if _utc(quote.timestamp_utc, "snapshot.timestamp_utc") != now:
                        _fail("overnight daily reference requires an exact boundary quote for every position", "DAILY_DRAWDOWN_REFERENCE_MISSING")
            reference = _number(equity, "daily_equity_reference", positive=True)
        else:
            reference = _number(initial_balance + math.fsum(balance_before_day_values), "daily_equity_reference", positive=True)
        references[day] = {"equity": reference, "persisted_at_utc": now.isoformat(), "halted": False}
    daily = references[day]
    drawdown = max(0.0, (daily["equity"] - equity) / daily["equity"] * 100)
    daily["halted"] = daily["halted"] or drawdown >= daily_limit
    state["known_trades"] = known
    state["last_observed_at_utc"] = now.isoformat()
    state["observed_valuation"] = {
        "balance": balance, "equity": equity, "realized_pnl": realized, "floating_pnl": floating,
        "daily_drawdown_pct": drawdown,
        "floating_drawdown_pct": max(0.0, (balance - equity) / balance * 100) if balance > 0 else None,
        "valued_at_utc": now.isoformat(), "trade_state_hash": paper_book_fingerprint(history),
    }
    if state != previous:
        try:
            database.update_operational_state({PAPER_DECISION_STATE_KEY: state})
        except Exception:
            _fail("paper capital or daily reference could not be persisted", "DAILY_DRAWDOWN_REFERENCE_MISSING")
        if _read_state(database) != state:
            _fail("paper capital or daily reference persistence was not verified", "DAILY_DRAWDOWN_REFERENCE_MISSING")
    _number(balance, "paper_balance", positive=True)
    _number(equity, "paper_equity", positive=True)
    consecutive_losses = 0
    for _, pnl in sorted(closed, key=lambda item: (item[0], -item[1]), reverse=True):
        if pnl >= 0:
            break
        consecutive_losses += 1
    kill_switch = KillSwitchState(active=bool(daily["halted"]), reason="PAPER_DAILY_DRAWDOWN_LIMIT", halted_until_utc=day_start + timedelta(days=1))
    return PaperDecisionState(
        account=replace(account_template, balance=balance, equity=equity, margin_free=0.0, currency=currency),
        risk_state=RiskRuntimeState(daily_equity_reference=daily["equity"], floating_drawdown_reference=balance, audit_confirmed=audit_confirmed, open_positions=tuple(positions), snapshots_by_symbol=used_snapshots, open_position_risk_amounts=risks, now_utc=now, consecutive_losses=consecutive_losses, kill_switch=kill_switch),
        initial_balance=initial_balance, realized_pnl=realized, floating_pnl=floating, operational_day=day,
        portfolio_open_trades=tuple({**trade.to_dict(), "risk_pct": risk / equity * 100.0, "risk_amount_current": risk} for trade, risk in marked_trades),
    )


def capture_paper_daily_reference(
    *, database: PaperStateStore, trades: Iterable[PaperTrade],
    snapshots_by_symbol: Mapping[str, MarketSnapshot], account_template: AccountState,
    now_utc: datetime, max_snapshot_age_seconds: float = 5,
    max_daily_drawdown_pct: float = 3.0,
) -> PaperDecisionState:
    """Capture a new UTC day only at its exact, fully observed market boundary.

    Existing references and latched halts are never replaced. A quote at 00:00:01
    is not evidence of midnight equity, even if it would pass normal freshness.
    All ordinary history, mark, provenance and persistence checks still run.
    """
    now = _utc(now_utc, "now_utc")
    if now.time() != datetime.min.time():
        _fail("daily boundary capture requires exactly midnight UTC", "DAILY_DRAWDOWN_REFERENCE_MISSING")
    for symbol, quote in snapshots_by_symbol.items():
        _validate_snapshot(quote, symbol, now, max_snapshot_age_seconds)
        if _utc(quote.timestamp_utc, "snapshot.timestamp_utc") != now:
            _fail("daily boundary capture requires exact boundary quotes", "DAILY_DRAWDOWN_REFERENCE_MISSING")
    return build_paper_decision_state(
        database=database, trades=trades, snapshots_by_symbol=snapshots_by_symbol,
        account_template=account_template, now_utc=now_utc,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
        max_daily_drawdown_pct=max_daily_drawdown_pct, _capture_daily_boundary=True,
    )


def _read_state(database: PaperStateStore) -> dict[str, Any] | None:
    try:
        outer = database.get_operational_state()
        if not isinstance(outer, Mapping):
            _fail("paper operational state is invalid")
        value = outer.get(PAPER_DECISION_STATE_KEY)
        if PAPER_DECISION_STATE_KEY in outer and not isinstance(value, dict):
            _fail("persisted paper decision state is invalid")
        return copy.deepcopy(value)
    except PaperStateError:
        raise
    except Exception:
        _fail("paper operational state cannot be read")


def _validate_state(state: dict[str, Any], currency: str, now: datetime) -> dict[str, Any]:
    required = {"schema_version", "initial_balance", "currency", "created_at_utc", "last_observed_at_utc", "daily_references", "known_trades"}
    if set(state) - {"observed_valuation"} != required or state["schema_version"] != "1.0" or state["currency"] != currency:
        _fail("persisted paper state schema or currency is incompatible")
    _number(state["initial_balance"], "initial_balance", positive=True)
    created = _utc(state["created_at_utc"], "created_at_utc")
    observed = _utc(state["last_observed_at_utc"], "last_observed_at_utc")
    if not created <= observed <= now:
        _fail("paper state clock moved backwards or baseline chronology is invalid")
    if not isinstance(state["known_trades"], dict) or not all(isinstance(value, dict) for value in state["known_trades"].values()):
        _fail("persisted paper history index is invalid")
    if not isinstance(state["daily_references"], dict):
        _fail("persisted daily references are invalid")
    for day, reference in state["daily_references"].items():
        if not isinstance(reference, dict) or set(reference) != {"equity", "persisted_at_utc", "halted"}:
            _fail("persisted daily equity reference is invalid")
        _number(reference["equity"], "daily_equity_reference", positive=True)
        stamp = _utc(reference["persisted_at_utc"], "persisted_at_utc")
        if day != stamp.date().isoformat() or stamp > now or type(reference["halted"]) is not bool:
            _fail("persisted daily equity reference date or halt is invalid")
    return state


def paper_book_fingerprint(trades: Iterable[PaperTrade | Mapping[str, Any]]) -> str:
    """Identify the exact economic book used by a persisted mark-to-market."""

    fields = ("paper_trade_id", "signal_id", "symbol", "broker_symbol", "direction", "entry_time_utc",
              "entry_price", "sl_price", "tp_price", "lot", "risk_amount", "commission_assumed",
              "status", "exit_time_utc", "exit_price", "profit", "raw_pnl", "scaled_paper_pnl",
              "pnl_formula_version", "paper_risk_multiplier", "risk_multiplier", "multiplier_applied")
    rows = []
    try:
        for trade in trades:
            payload = trade.to_dict() if isinstance(trade, PaperTrade) else trade
            row = {field: payload.get(field) for field in fields}
            row["pnl_basis"] = payload.get("metadata", {}).get("pnl_basis")
            rows.append(row)
        encoded = json.dumps(sorted(rows, key=lambda row: row["paper_trade_id"]), sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (AttributeError, TypeError, ValueError):
        _fail("paper book cannot be fingerprinted")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_snapshot(snapshot: MarketSnapshot | None, symbol: str, now: datetime, max_age: float) -> None:
    if not isinstance(snapshot, MarketSnapshot) or snapshot.symbol != symbol:
        _fail("an open paper position has no matching market snapshot")
    age = (now - _utc(snapshot.timestamp_utc, "snapshot.timestamp_utc")).total_seconds()
    if not 0 <= age <= max_age:
        _fail("an open paper position has a stale or future market snapshot")
    for field in ("bid", "ask", "point", "tick_size", "tick_value", "volume_min", "volume_max", "volume_step"):
        _number(getattr(snapshot, field), field, positive=True)
    _number(snapshot.spread_points, "spread_points", nonnegative=True)
    if not all(is_price_on_tick_grid(getattr(snapshot, field), snapshot.tick_size) for field in ("bid", "ask")):
        _fail("open paper quote is outside the instrument tick grid")
    for field in ("digits", "stops_level_points", "freeze_level_points"):
        value = getattr(snapshot, field)
        if type(value) is not int or value < 0:
            _fail("open paper instrument precision or stop metadata is invalid")
    try:
        snapshot.validate()
    except (TypeError, ValueError):
        _fail("open paper instrument market metadata is invalid")


def _utc(value: Any, field: str) -> datetime:
    try:
        instant = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(instant, datetime) or instant.utcoffset() is None:
            raise ValueError
        return instant.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        _fail(f"{field} must be an explicit timezone-aware datetime")


def _number(value: Any, field: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
        if not valid or (positive and value <= 0) or (nonnegative and value < 0):
            raise ValueError
        return float(value)
    except (TypeError, ValueError, OverflowError):
        _fail(f"{field} has an invalid numeric value")


def _fail(message: str, code: str = "RISK_CALCULATION_UNCERTAIN") -> Any:
    raise PaperStateError(message, source="paper_decision_state", detail={"reject_code": code}) from None
