"""Demo-only MT5 execution of the forward value book (decision 2026-10-30).

The paper record decides; this module only mirrors it on the demo account.
Each run reconciles the account with the book's open paper trades:

- **Close** a demo position whose paper trade closed (a rebalance or a flip).
- **Move** a demo position's stop loss and take-profit to the paper trade's
  latest levels after a re-anchor.
- **Open** a paper trade that has no demo position yet. A trade whose demo
  position was closed by the broker (its stop loss or take-profit hit
  intraday) is never reopened.

Every order goes through ``demo_release_gate`` first, and again before each
send. Each new position is checked as follows:

- it has a stop loss and a take-profit on the right side of the price,
  outside the broker's stops level;
- its lot comes from ``PositionSizer`` (``Capital × Riesgo% / riesgo por
  lote``, rounded down to the broker's step) at the paper trade's risk,
  capped at ``MAX_RISK_PER_TRADE_PCT``;
- the risk to the stop of every open position of this book, plus the new
  one, stays within ``MAX_OPEN_RISK_PCT`` of equity;
- the account holds at most ``MAX_OPEN_TRADES`` positions;
- no new position opens while the floating loss reaches
  ``MAX_FLOATING_DRAWDOWN_PCT`` of balance, or the loss since the first run
  of the UTC day reaches ``MAX_DAILY_DRAWDOWN_PCT``;
- the spread is at most 5% of the stop distance. A monthly book's stops sit
  hundreds of pips away, so a fixed point limit would block the
  Scandinavian pairs forever.

Every request is written to an append-only journal and flushed to disk before
it is sent, and its result is written after. The state file maps paper trade
ids to tickets, so a rerun never opens the same trade twice. Nothing here
can reach a real account: the gate refuses any account whose trade mode is
not demo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Sequence

from ..config import BotConfig
from ..contracts import Direction, MarketSnapshot
from ..research.daily_fx.forward_trades import PaperTrade
from ..risk.position_sizer import PositionSizer
from .release_policy import demo_release_gate

MAGIC = 26102026
DEVIATION_POINTS = 20
MAX_SPREAD_SHARE_OF_STOP = 0.05
DONE_RETCODES = {10008, 10009, 10010}  # placed, done, done partially
TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
ORDER_TIME_GTC = 0
FILLING_FOK, FILLING_IOC, FILLING_RETURN = 0, 1, 2


@dataclass
class DemoRun:
    """What one reconciliation did; ``events`` feed the Telegram messages."""

    released: bool
    code: str
    detail: str = ""
    opened: list[dict[str, Any]] = field(default_factory=list)
    closed: list[dict[str, Any]] = field(default_factory=list)
    modified: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"released": self.released, "code": self.code, "detail": self.detail, "opened": self.opened,
                "closed": self.closed, "modified": self.modified, "skipped": self.skipped, "failed": self.failed}


class DemoJournal:
    """Append-only JSONL journal (fsynced before each send) and the trade-id → ticket state."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.journal = folder / "demo_journal.jsonl"
        self.state_path = folder / "demo_state.json"
        self.state: dict[str, Any] = (json.loads(self.state_path.read_text(encoding="utf-8"))
                                      if self.state_path.exists() else {"trades": {}, "day": {}})

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps({"at_utc": datetime.now(timezone.utc).isoformat(), **record}, sort_keys=True,
                          default=str)
        with self.journal.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def save(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)


def _filling(info: Any) -> int:
    mode = int(getattr(info, "filling_mode", 0) or 0)
    if mode & 2:
        return FILLING_IOC
    if mode & 1:
        return FILLING_FOK
    return FILLING_RETURN


def _snapshot(symbol: str, info: Any, tick: Any) -> MarketSnapshot:
    point = float(info.point)
    return MarketSnapshot(
        symbol=symbol, timeframe="D1", timestamp_utc=datetime.now(timezone.utc), bid=float(tick.bid),
        ask=float(tick.ask), spread_points=(float(tick.ask) - float(tick.bid)) / point, digits=int(info.digits),
        point=point, tick_value=float(info.trade_tick_value), tick_size=float(info.trade_tick_size),
        volume_min=float(info.volume_min), volume_max=float(info.volume_max), volume_step=float(info.volume_step),
        stops_level_points=int(getattr(info, "trade_stops_level", 0) or 0),
        freeze_level_points=int(getattr(info, "trade_freeze_level", 0) or 0))


def _position_risk(position: Any, info: Any) -> float:
    if not position.sl:
        return float("inf")  # a position of this book without a stop is never acceptable
    ticks = abs(float(position.price_open) - float(position.sl)) / float(info.trade_tick_size)
    return ticks * float(info.trade_tick_value) * float(position.volume)


def _levels_valid(side: str, snapshot: MarketSnapshot, sl: float, tp: float) -> str:
    gap = max(snapshot.stops_level_points, snapshot.freeze_level_points) * snapshot.point
    if side == "BUY" and not (sl < snapshot.bid - gap and tp > snapshot.ask + gap):
        return "LEVELS_INVALID: the price is already beyond the stop loss or take-profit"
    if side == "SELL" and not (sl > snapshot.ask + gap and tp < snapshot.bid - gap):
        return "LEVELS_INVALID: the price is already beyond the stop loss or take-profit"
    return ""


class ValueDemoExecutor:
    """Reconcile the demo account with the paper book through ``demo_release_gate``."""

    def __init__(self, config: BotConfig, client: Any, journal: DemoJournal,
                 symbol_map: dict[str, str] | None = None, sizer: PositionSizer | None = None) -> None:
        self.config = config
        self.client = client
        self.journal = journal
        self.symbol_map = symbol_map or {}
        self.sizer = sizer or PositionSizer()

    # --- gate and account -----------------------------------------------------------------------------------

    def _gate(self) -> tuple[bool, str, str, Any]:
        account = self.client.account_info()
        demo = int(getattr(self.client, "ACCOUNT_TRADE_MODE_DEMO", 0))
        allowed, code, detail = demo_release_gate(self.config, account, self.client.terminal_info(), demo)
        return allowed, code, detail, account

    def _own_positions(self) -> list[Any]:
        return [position for position in (self.client.positions_get() or ()) if int(position.magic) == MAGIC]

    def _send(self, run: DemoRun, kind: str, trade_id: str, request: dict[str, Any]) -> Any:
        allowed, code, detail, _ = self._gate()  # checked again right before every order
        if not allowed:
            run.failed.append({"trade_id": trade_id, "kind": kind, "reason": f"{code}: {detail}"})
            return None
        self.journal.write({"event": "REQUEST", "kind": kind, "trade_id": trade_id, "request": request})
        started = time.perf_counter()
        result = self.client.order_send(request)
        elapsed_ms = round(1000.0 * (time.perf_counter() - started), 1)
        retcode = getattr(result, "retcode", None)
        self.journal.write({"event": "RESULT", "kind": kind, "trade_id": trade_id, "retcode": retcode,
                            "order": getattr(result, "order", None), "deal": getattr(result, "deal", None),
                            "comment": getattr(result, "comment", None), "send_ms": elapsed_ms})
        if result is None or retcode not in DONE_RETCODES:
            run.failed.append({"trade_id": trade_id, "kind": kind,
                               "reason": f"retcode {retcode}: {getattr(result, 'comment', '') or self.client.last_error()}"})
            return None
        return result

    # --- reconciliation -------------------------------------------------------------------------------------

    def run(self, trades: Sequence[PaperTrade]) -> DemoRun:
        allowed, code, detail, account = self._gate()
        run = DemoRun(released=allowed, code=code, detail=detail)
        if not allowed:
            return run
        state = self.journal.state
        records: dict[str, dict[str, Any]] = state.setdefault("trades", {})
        wanted = {trade.trade_id: trade for trade in trades if trade.closed_on is None}
        positions = {int(position.ticket): position for position in self._own_positions()}
        # Positions closed by the broker (stop loss or take-profit hit intraday) are not reopened.
        for trade_id, record in records.items():
            if record.get("status") == "OPEN" and int(record["ticket"]) not in positions:
                record["status"] = "CLOSED_BY_BROKER"
                run.closed.append({"trade_id": trade_id, "ticket": record["ticket"], "by": "broker (SL/TP)"})
        self.journal.save()
        for trade_id, record in records.items():
            if record.get("status") != "OPEN":
                continue
            position = positions.get(int(record["ticket"]))
            if position is None:
                continue
            trade = wanted.get(trade_id)
            if trade is None:
                self._close(run, trade_id, record, position)
            else:
                self._move_levels(run, trade, position)
        known = {int(record["ticket"]) for record in records.values() if "ticket" in record}
        for ticket, position in positions.items():
            if ticket not in known:
                run.skipped.append({"ticket": ticket, "symbol": position.symbol,
                                    "reason": "UNKNOWN_POSITION: left untouched; check it in MT5"})
        self._remember_day(account)
        for trade_id, trade in wanted.items():
            if trade_id not in records:
                self._open(run, trade)
        self.journal.save()
        return run

    def _remember_day(self, account: Any) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        day = self.journal.state.setdefault("day", {})
        if day.get("date") != today:
            day.update({"date": today, "equity": float(account.equity)})

    def _broker_symbol(self, trade: PaperTrade) -> str:
        return self.symbol_map.get(trade.symbol, trade.symbol)

    def _close(self, run: DemoRun, trade_id: str, record: dict[str, Any], position: Any) -> None:
        tick = self.client.symbol_info_tick(position.symbol)
        buy = int(position.type) == ORDER_TYPE_BUY
        request = {"action": TRADE_ACTION_DEAL, "symbol": position.symbol, "volume": float(position.volume),
                   "type": ORDER_TYPE_SELL if buy else ORDER_TYPE_BUY, "position": int(position.ticket),
                   "price": float(tick.bid if buy else tick.ask), "deviation": DEVIATION_POINTS, "magic": MAGIC,
                   "comment": f"afx close {trade_id}"[:31], "type_time": ORDER_TIME_GTC,
                   "type_filling": _filling(self.client.symbol_info(position.symbol))}
        if self._send(run, "CLOSE", trade_id, request) is not None:
            record["status"] = "CLOSED_BY_BOOK"
            run.closed.append({"trade_id": trade_id, "ticket": int(position.ticket), "by": "rebalanceo",
                               "price": request["price"], "profit": float(getattr(position, "profit", 0.0))})

    def _move_levels(self, run: DemoRun, trade: PaperTrade, position: Any) -> None:
        sl, tp = trade.current_stop_loss, trade.current_take_profit
        info = self.client.symbol_info(position.symbol)
        if sl is None or tp is None or info is None:
            return
        digits = int(info.digits)
        sl, tp = round(sl, digits), round(tp, digits)
        if abs(sl - float(position.sl)) < float(info.point) and abs(tp - float(position.tp)) < float(info.point):
            return
        snapshot = _snapshot(position.symbol, info, self.client.symbol_info_tick(position.symbol))
        problem = _levels_valid(trade.side, snapshot, sl, tp)
        if problem:
            run.skipped.append({"trade_id": trade.trade_id, "reason": problem})
            return
        request = {"action": TRADE_ACTION_SLTP, "symbol": position.symbol, "position": int(position.ticket),
                   "sl": sl, "tp": tp, "magic": MAGIC}
        if self._send(run, "SLTP", trade.trade_id, request) is not None:
            run.modified.append({"trade_id": trade.trade_id, "ticket": int(position.ticket), "sl": sl, "tp": tp})

    def _open(self, run: DemoRun, trade: PaperTrade) -> None:
        symbol = self._broker_symbol(trade)
        skip = lambda reason: run.skipped.append({"trade_id": trade.trade_id, "symbol": symbol, "reason": reason})
        sl, tp = trade.current_stop_loss, trade.current_take_profit
        if sl is None or tp is None or trade.current_risk_percent is None:
            skip("NO_LEVELS: the paper trade has no stop loss or take-profit")
            return
        self.client.symbol_select(symbol, True)
        info, tick = self.client.symbol_info(symbol), self.client.symbol_info_tick(symbol)
        if info is None or tick is None:
            skip("SYMBOL_UNAVAILABLE")
            return
        if int(getattr(info, "trade_mode", 4)) != 4:  # SYMBOL_TRADE_MODE_FULL
            skip("SYMBOL_NOT_TRADABLE")
            return
        account = self.client.account_info()
        equity, balance = float(account.equity), float(account.balance)
        if balance <= 0 or equity <= 0:
            skip("ACCOUNT_INVALID")
            return
        if (balance - equity) / balance * 100.0 >= self.config.max_floating_drawdown_pct:
            skip("FLOATING_DRAWDOWN_LIMIT")
            return
        start = float(self.journal.state.get("day", {}).get("equity") or equity)
        if (start - equity) / start * 100.0 >= self.config.max_daily_drawdown_pct:
            skip("DAILY_DRAWDOWN_LIMIT")
            return
        all_positions = list(self.client.positions_get() or ())
        if len(all_positions) + 1 > self.config.max_open_trades:
            skip("MAX_OPEN_TRADES")
            return
        digits = int(info.digits)
        sl, tp = round(sl, digits), round(tp, digits)
        snapshot = _snapshot(symbol, info, tick)
        problem = _levels_valid(trade.side, snapshot, sl, tp)
        if problem:
            skip(problem)
            return
        entry = snapshot.ask if trade.side == "BUY" else snapshot.bid
        if (snapshot.ask - snapshot.bid) > MAX_SPREAD_SHARE_OF_STOP * abs(entry - sl):
            skip("SPREAD_TOO_WIDE")
            return
        risk_pct = min(float(trade.current_risk_percent), self.config.max_risk_per_trade_pct)
        sizing = self.sizer.size_for_risk(
            equity=equity, risk_pct=risk_pct, direction=Direction.BUY if trade.side == "BUY" else Direction.SELL,
            sl_price=sl, snapshot=snapshot, entry_price=entry)
        if not sizing.valid:
            skip(f"LOT_INVALID: {sizing.reason}")
            return
        open_risk = sum(_position_risk(position, self.client.symbol_info(position.symbol))
                        for position in self._own_positions())
        if open_risk + sizing.risk_amount > equity * self.config.max_open_risk_pct / 100.0:
            skip("MAX_OPEN_RISK")
            return
        request = {"action": TRADE_ACTION_DEAL, "symbol": symbol, "volume": sizing.lot,
                   "type": ORDER_TYPE_BUY if trade.side == "BUY" else ORDER_TYPE_SELL, "price": entry, "sl": sl,
                   "tp": tp, "deviation": DEVIATION_POINTS, "magic": MAGIC, "comment": f"afx {trade.trade_id}"[:31],
                   "type_time": ORDER_TIME_GTC, "type_filling": _filling(info)}
        result = self._send(run, "OPEN", trade.trade_id, request)
        if result is None:
            return
        ticket = int(getattr(result, "order", 0) or 0)
        self.journal.state["trades"][trade.trade_id] = {"ticket": ticket, "status": "OPEN", "symbol": symbol,
                                                        "side": trade.side, "lot": sizing.lot}
        run.opened.append({"trade_id": trade.trade_id, "ticket": ticket, "symbol": symbol, "side": trade.side,
                           "lot": sizing.lot, "price": entry, "sl": sl, "tp": tp,
                           "risk_percent": round(sizing.risk_pct, 3), "risk_amount": round(sizing.risk_amount, 2)})


def load_symbol_map(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
