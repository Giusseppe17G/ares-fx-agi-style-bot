"""Open paper trade lifecycle audit for Micro V2."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping

from agi_style_forex_bot_mt5.paper_trading.paper_pnl_engine import calculate_scaled_paper_pnl
from agi_style_forex_bot_mt5.utils.safe_datetime import safe_parse_datetime


STALE_TRADE_AGE_MINUTES = 24 * 60


def audit_open_trade_lifecycle(
    dataset: Mapping[str, Any],
    *,
    profile_config: str,
    stale_symbols: list[str] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stale_set = {symbol.upper() for symbol in (stale_symbols or [])}
    open_trades = [trade for trade in dataset.get("paper_trades", []) if str(trade.get("status", "")).upper() == "OPEN"]
    duplicate_ids = {trade_id for trade_id, count in Counter(_trade_id(trade) for trade in open_trades).items() if trade_id and count > 1}
    latest_prices = _latest_prices(dataset.get("events", []))
    rows: list[dict[str, Any]] = []
    for trade in open_trades:
        symbol = str(trade.get("symbol") or "").upper()
        current_price = _first_float(trade.get("current_price"), trade.get("mark_price"), latest_prices.get(symbol))
        entry = _first_float(trade.get("entry_price"), trade.get("open_price"), trade.get("price"))
        sl = _first_float(trade.get("sl_price"), trade.get("stop_loss"), trade.get("sl"))
        tp = _first_float(trade.get("tp_price"), trade.get("take_profit"), trade.get("tp"))
        risk_distance = abs(entry - sl) if entry is not None and sl is not None else None
        reward_distance = abs(tp - entry) if entry is not None and tp is not None else None
        age_minutes = _age_minutes(trade.get("opened_at_utc") or trade.get("entry_time_utc"), now)
        calc_trade = {**trade, "current_price": current_price} if current_price is not None else dict(trade)
        pnl = calculate_scaled_paper_pnl(calc_trade, profile_config=profile_config) if current_price is not None else {}
        row = {
            "trade_id": _trade_id(trade),
            "symbol": symbol,
            "side": str(trade.get("side") or trade.get("direction") or "").upper(),
            "entry_price": entry,
            "current_price": current_price,
            "sl_price": sl,
            "tp_price": tp,
            "opened_at_utc": trade.get("opened_at_utc") or trade.get("entry_time_utc") or "",
            "age_minutes": age_minutes,
            "risk_distance": risk_distance,
            "reward_distance": reward_distance,
            "estimated_r_multiple": _r_multiple(entry, current_price, sl, trade),
            "raw_paper_pnl": _first_float(trade.get("raw_pnl"), pnl.get("raw_pnl")),
            "scaled_paper_pnl": _first_float(trade.get("scaled_paper_pnl"), pnl.get("scaled_paper_pnl")),
            "latent_paper_pnl": _first_float(trade.get("latent_paper_pnl"), trade.get("unrealized_pnl"), pnl.get("scaled_paper_pnl")),
            "sl_equals_entry": entry is not None and sl is not None and abs(entry - sl) <= 1e-12,
            "tp_equals_entry": entry is not None and tp is not None and abs(tp - entry) <= 1e-12,
            "missing_sl": sl is None,
            "missing_tp": tp is None,
            "missing_current_price": current_price is None,
            "invalid_risk_distance": risk_distance is not None and risk_distance <= 0,
            "invalid_sl_tp": sl is None or tp is None or (entry is not None and (abs(entry - sl) <= 1e-12 or abs(tp - entry) <= 1e-12)),
            "symbol_stale": symbol in stale_set,
            "trade_too_old": age_minutes is not None and age_minutes > STALE_TRADE_AGE_MINUTES,
            "trailing_state_exists": bool(trade.get("trailing_state") or trade.get("trailing_stop")),
            "exit_condition_evaluated": _has_trade_event(dataset.get("events", []), _trade_id(trade), {"EXIT", "CLOSE", "TP", "SL"}),
            "paper_close_notification_ready": current_price is not None and not (risk_distance is None or risk_distance <= 0),
            "duplicate_trade_id": _trade_id(trade) in duplicate_ids,
            "exposure_inconsistent": False,
            "pnl_formula_version": pnl.get("pnl_formula_version", ""),
            "pnl_scaling_status": pnl.get("pnl_scaling_status", ""),
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
        rows.append(row)
    invalid_risk = sum(1 for row in rows if row["invalid_risk_distance"])
    invalid_sl_tp = sum(1 for row in rows if row["invalid_sl_tp"])
    invalid_unique = sum(1 for row in rows if row["invalid_risk_distance"] or row["invalid_sl_tp"])
    missing_price = sum(1 for row in rows if row["missing_current_price"])
    return {
        "open_trade_count": len(rows),
        "invalid_open_trade_count": invalid_unique,
        "risk_distance_issues": invalid_risk,
        "sl_tp_issues": invalid_sl_tp,
        "missing_current_price_count": missing_price,
        "duplicate_trade_id_count": sum(1 for row in rows if row["duplicate_trade_id"]),
        "stale_symbol_open_trade_count": sum(1 for row in rows if row["symbol_stale"]),
        "open_trades": rows,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _latest_prices(events: list[Mapping[str, Any]]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for event in events:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        symbol = str(event.get("symbol") or payload.get("symbol") or "").upper()
        if not symbol:
            continue
        price = _first_float(payload.get("current_price"), payload.get("last_price"), payload.get("mid"), payload.get("bid"), payload.get("ask"))
        if price is not None:
            prices[symbol] = price
    return prices


def _has_trade_event(events: list[Mapping[str, Any]], trade_id: str, markers: set[str]) -> bool:
    if not trade_id:
        return False
    for event in events:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        text = f"{event.get('event_type', '')} {event.get('message', '')} {payload}".upper()
        if trade_id.upper() in text and any(marker in text for marker in markers):
            return True
    return False


def _age_minutes(value: Any, now: datetime) -> float | None:
    parsed = safe_parse_datetime(value, field_name="opened_at_utc", source="micro_v2_lifecycle")
    if parsed.value is None:
        return None
    return round(max((now - parsed.value.astimezone(timezone.utc)).total_seconds(), 0.0) / 60.0, 4)


def _r_multiple(entry: float | None, current: float | None, sl: float | None, trade: Mapping[str, Any]) -> float | None:
    if entry is None or current is None or sl is None or abs(entry - sl) <= 1e-12:
        return None
    move = current - entry
    if str(trade.get("side") or trade.get("direction") or "").upper() == "SELL":
        move *= -1
    return round(move / abs(entry - sl), 6)


def _trade_id(trade: Mapping[str, Any]) -> str:
    return str(trade.get("paper_trade_id") or trade.get("trade_id") or trade.get("id") or "")


def _first_float(*values: Any) -> float | None:
    for value in values:
        try:
            if value is None or value == "":
                continue
            return float(value)
        except Exception:
            continue
    return None
