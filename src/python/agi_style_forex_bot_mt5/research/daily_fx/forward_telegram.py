"""Telegram messages of the forward paper tracking, in the style of a trading channel (research only).

From the rebuilt paper trades and the sealed record, this module writes:

- one message when the tracking starts, with the positions already open;
- one message per trade opened (pair, side, entry, stop loss, take-profit,
  risk);
- one message per trade closed (exit, pips, result, reason, duration);
- one summary per complete week:
  - the week's and the cumulative result, from the sealed returns (net of
    the study's costs);
  - trades closed, wins and losses, win rate and profit factor;
  - maximum drawdown and open positions;
  - the rule's status and the broker-swap coverage;
- one message per annual look and per final status;
- alerts with what to do when the routine stops.

Every message says it is paper and ends with the disclaimer (estimated
costs, not real money, not a recommendation). Each one has a stable key, so a
rerun never
repeats it: it is queued in the existing durable outbox and sent once.
Nothing here reads an account or sends an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import pandas as pd

from .forward_trades import REASONS, PaperTrade, TradeBook

PAPER = "papel"
DISCLAIMER = "⚠️ Simulación en papel con costes estimados. No es dinero real ni una recomendación."
STATUS_TEXT = {
    "ONGOING": "EN CURSO",
    "CONFIRMED": "CONFIRMADA",
    "ABANDONED_FUTILITY": "ABANDONADA (sin resultados suficientes)",
    "ABANDONED_DRAWDOWN": "ABANDONADA (caída máxima alcanzada)",
    "ENDED_WITHOUT_CONFIRMATION": "TERMINADA SIN CONFIRMAR",
}
# What the operator should do when the routine stops, by refusal code.
ALERT_ACTIONS = {
    "PRICES_STALE": "Un par no se exportó esta vez. Repite la exportación y vuelve a correr.",
    "PRICES_TOO_SHORT": "Falta histórico diario: exporta con más --bars.",
    "PRICES_MISSING": "Falta el archivo de un par: añádelo a la Observación de mercado y exporta.",
    "FORWARD_HISTORY_CHANGED": "El bróker cambió datos antiguos o falta uno. No borres nada y avisa.",
    "PLAN_MISMATCH": "No se está ejecutando desde la copia fija del código. Vuelve a crearla.",
    "ENGINE_CHANGED": "No se está ejecutando desde la copia fija del código. Vuelve a crearla.",
    "INFLATION_BASE_CHANGED": "El cpi.csv no es el fijado. Vuelve a copiarlo.",
    "LEDGER_MISMATCH": "El ledger no corresponde a este plan. No lo borres y avisa.",
    "EXPORT_INCOMPLETE": "La exportación de MT5 no trajo los 9 pares. Revisa MT5 y repite.",
    "MT5_UNAVAILABLE": "MT5 no está disponible (terminal cerrado o sin sesión). Ábrelo y repite.",
    "INFLATION_FETCH_FAILED": "No se pudo descargar la inflación nueva. Se reintentará la próxima vez.",
    "WAITING_FOR_INFLATION": "Falta la inflación de un año nuevo. Se descargará cuando el Banco Mundial la publique.",
    "SWAP_CAPTURE_FAILED": "No se pudo capturar el swap. La cobertura del swap real baja; revisa el mapa de símbolos.",
    "RECORD_MISMATCH": "El informe no reproduce el registro sellado. No borres nada y avisa.",
    "TRADES_MISMATCH": "Las operaciones del informe no cuadran con el motor. El registro sigue válido; avisa.",
}


@dataclass(frozen=True)
class Message:
    key: str
    kind: str
    on: str  # yyyy-mm-dd, for ordering
    order: int
    text: str


def _pct(value: float, signed: bool = True) -> str:
    text = f"{value:+.2f}%" if signed else f"{value:.2f}%"
    return text.replace(".", ",")


def _number(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _price(symbol: str, value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "-"
    return f"{value:.3f}" if symbol.endswith("JPY") else f"{value:.5f}"


def _day(text: str) -> str:
    stamp = pd.Timestamp(text)
    return f"{stamp.day:02d}-{stamp.month:02d}-{stamp.year}"


def _side(trade: PaperTrade) -> str:
    return "COMPRA" if trade.side == "BUY" else "VENTA"


def _icon(value: float) -> str:
    return "✅" if value > 0.005 else "❌" if value < -0.005 else "⚪"


def open_message(trade: PaperTrade) -> Message:
    icon = "🟢" if trade.side == "BUY" else "🔴"
    text = "\n".join([
        f"{icon} {_side(trade)} {trade.symbol} · {PAPER}",
        f"Entrada: {_price(trade.symbol, trade.open_price)}",
        f"Stop loss: {_price(trade.symbol, trade.stop_loss)} · Take profit: {_price(trade.symbol, trade.take_profit)}",
        f"Riesgo hasta el stop: {_number(trade.risk_percent)}% del capital (máximo 0,50%)",
        f"Abierta el {_day(trade.opened_on)} en el rebalanceo · estrategia valor real 5 años",
        DISCLAIMER,
    ])
    return Message(f"forward:open:{trade.trade_id}", "open", trade.opened_on, 2, text)


def close_message(trade: PaperTrade, forward_start: str) -> Message:
    days = (pd.Timestamp(trade.closed_on) - pd.Timestamp(trade.opened_on)).days
    since = f" desde el inicio del seguimiento ({_day(forward_start)})" if trade.opened_before_start else ""
    lines = [
        f"{_icon(trade.pnl_percent)} CERRADA {_side(trade)} {trade.symbol} · {REASONS[trade.reason]} · {PAPER}",
        f"Entrada {_price(trade.symbol, trade.open_price)} ({_day(trade.opened_on)}) → "
        f"Salida {_price(trade.symbol, trade.close_price)} ({trade.pips:+.0f} pips)",
        f"Resultado{since}: {_pct(trade.pnl_percent)} del capital (bruto, antes de costes)",
        f"Duración: {days} días",
        DISCLAIMER,
    ]
    return Message(f"forward:close:{trade.trade_id}", "close", trade.closed_on, 1, "\n".join(lines))


def _rule_line(rule: dict[str, Any]) -> str:
    status = rule.get("status", "ONGOING")
    text = f"Regla: {STATUS_TEXT.get(status, status)}"
    if status == "ONGOING" and rule.get("next_look"):
        text += f" · próxima revisión {_day(rule['next_look'])}"
    return text


def _closed_stats(trades: Iterable[PaperTrade]) -> tuple[int, int, int, float | None, float | None]:
    results = [trade.pnl_percent for trade in trades]
    wins = [value for value in results if value > 0]
    losses = [value for value in results if value < 0]
    rate = 100.0 * len(wins) / len(results) if results else None
    factor = (sum(wins) / -sum(losses)) if losses else None
    return len(results), len(wins), len(losses), rate, factor


def weekly_messages(book: TradeBook) -> list[Message]:
    """One summary per complete week (Monday to Friday) on or after the forward start."""

    returns = book.daily_returns
    if returns.empty:
        return []
    through = pd.Timestamp(book.through_day, tz="UTC")
    start = pd.Timestamp(book.forward_start, tz="UTC")
    first_monday = start - pd.Timedelta(days=start.dayofweek)
    complete = ((through - first_monday).days - 4) // 7 + 1  # weeks whose Friday is sealed
    mondays = [first_monday + pd.Timedelta(days=7 * week) for week in range(max(complete, 0))]
    messages = []
    for monday in mondays:
        friday = monday + pd.Timedelta(days=4)
        week = returns.loc[monday:friday + pd.Timedelta(hours=23)]
        to_date = returns.loc[:friday + pd.Timedelta(hours=23)]
        equity = to_date.cumsum().to_numpy()
        peak = np.maximum.accumulate(np.r_[0.0, equity])[1:]
        drawdown = 100.0 * (1.0 - float(np.exp(-(peak - equity).max()))) if len(equity) else 0.0
        week_end = str(friday.date())
        closed_week = [trade for trade in book.closed() if str(monday.date()) <= trade.closed_on <= week_end]
        closed_all = [trade for trade in book.closed() if trade.closed_on <= week_end]
        total, wins, losses, rate, factor = _closed_stats(closed_all)
        week_total, week_wins, week_losses, _, _ = _closed_stats(closed_week)
        swap = book.swap_returns.loc[:friday + pd.Timedelta(hours=23)]
        coverage = 100.0 * float(swap.notna().mean()) if len(swap) else 0.0
        lines = [
            f"📊 Resumen semanal {_day(str(monday.date()))} a {_day(week_end)} · {PAPER}",
            f"Semana: {_pct(100.0 * float(np.expm1(week.sum())))} · "
            f"Acumulado: {_pct(100.0 * float(np.expm1(to_date.sum())))}",
            f"Cerradas esta semana: {week_total} (✅ {week_wins} · ❌ {week_losses})",
            f"Cerradas desde el inicio: {total} (✅ {wins} · ❌ {losses})"
            + (f" · acierto {_number(rate, 0)}%" if rate is not None else "")
            + (f" · factor de beneficio {_number(factor)}" if factor is not None else ""),
            f"Caída máxima: {_pct(drawdown, signed=False)}",
        ]
        if monday == mondays[-1]:
            positions = [f"{_side(trade)} {trade.symbol} {_pct(trade.pnl_percent)}" for trade in book.open()]
            lines.append(f"Abiertas ({len(positions)}): " + (" · ".join(positions) if positions else "ninguna"))
            lines.append(_rule_line(book.rule))
        lines.append(f"Swap real del bróker cubierto: {_number(coverage, 0)}% de los días")
        lines.append(DISCLAIMER)
        iso = friday.isocalendar()
        messages.append(Message(f"forward:week:{iso[0]}-W{iso[1]:02d}", "week", week_end, 3, "\n".join(lines)))
    return messages


def start_message(book: TradeBook) -> Message:
    already = [trade for trade in book.trades if trade.opened_before_start]
    lines = [
        f"▶️ Seguimiento en {PAPER} iniciado · estrategia valor real 5 años · 9 pares contra USD",
        "Riesgo máximo 0,5% del capital por operación · stop loss y take profit siempre · "
        "rebalanceo cada 21 días hábiles",
        "Posiciones abiertas al inicio: " + (" · ".join(
            f"{_side(trade)} {trade.symbol} (desde {_day(trade.opened_on)})" for trade in already) or "ninguna"),
        DISCLAIMER,
    ]
    return Message("forward:start", "start", book.forward_start, 0, "\n".join(lines))


def rule_messages(book: TradeBook) -> list[Message]:
    messages = []
    for look in book.rule.get("looks", []):
        t_value = look.get("t")
        text = (f"🏁 Revisión anual {look['look']} ({_day(look['on'])}) · {PAPER}\n"
                f"t de Newey-West: {_number(t_value) if t_value is not None else '-'} "
                f"(hace falta {_number(look['boundary'])} para confirmar)\n"
                f"Swap real cubierto: {_number(100.0 * look['swap_coverage'], 0)}% de los días")
        if look.get("confirmation_withheld"):
            text += "\nConfirmación retenida: el swap real no cubre lo suficiente o su total no es positivo."
        text += f"\n{DISCLAIMER}"
        messages.append(Message(f"forward:look:{look['look']}", "look", look["on"], 4, text))
    status = book.rule.get("status", "ONGOING")
    if status != "ONGOING":
        text = (f"🏁 Estado final del seguimiento: {STATUS_TEXT.get(status, status)} ({_day(book.rule['on'])}) · "
                f"{PAPER}\nEl registro queda cerrado. Ningún resultado activa operaciones reales.\n{DISCLAIMER}")
        messages.append(Message(f"forward:final:{status}", "final", book.rule["on"], 5, text))
    return messages


def alert_message(code: str, detail: str = "", on: str | None = None) -> Message:
    day = on or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    action = ALERT_ACTIONS.get(code, "Revisa la salida de la rutina.")
    text = (f"⚠️ Seguimiento en {PAPER}: {code}\n{action}" + (f"\nDetalle: {detail[:500]}" if detail else "")
            + f"\n{DISCLAIMER}")
    return Message(f"forward:alert:{code}:{day}", "alert", day, 9, text)


def build_messages(book: TradeBook) -> list[Message]:
    """Every message the record supports, in date order (a rerun skips those already sent)."""

    if book.daily_returns.empty:
        return []
    messages = [start_message(book)]
    messages += [open_message(trade) for trade in book.trades if not trade.opened_before_start]
    messages += [close_message(trade, book.forward_start) for trade in book.closed()]
    messages += weekly_messages(book)
    messages += rule_messages(book)
    return sorted(messages, key=lambda item: (item.on, item.order, item.key))


def deliver(messages: Sequence[Message], notifier: Any, preview: Path | None = None,
            pause_seconds: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> dict[str, int]:
    """Queue and send each message once; append new ones to a local preview file."""

    counts = {"sent": 0, "skipped": 0, "disabled": 0, "failed": 0}
    for message in messages:
        result = notifier.send_text(idempotency_key=message.key, text=message.text,
                                    payload={"kind": message.kind, "on": message.on})
        status = result.status.lower()
        counts[status if status in counts else "failed"] += 1
        if result.status != "SKIPPED" and preview is not None:
            preview.parent.mkdir(parents=True, exist_ok=True)
            with preview.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"[{message.on}] {message.key} ({result.status})\n{message.text}\n\n")
        if result.status == "SENT" and pause_seconds > 0:
            sleep(pause_seconds)  # Telegram allows about one message per second per chat
    return counts
