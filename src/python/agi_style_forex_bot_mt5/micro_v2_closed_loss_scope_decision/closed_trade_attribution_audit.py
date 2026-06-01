"""Closed paper trade attribution audit."""

from __future__ import annotations

from typing import Any, Mapping


def audit_closed_trade_attribution(dataset: Mapping[str, Any]) -> dict[str, Any]:
    trades = list(dataset.get("paper_trades", []))
    closed = [trade for trade in trades if str(trade.get("status", "")).upper() == "CLOSED"]
    quarantined_ids = {str(trade.get("paper_trade_id") or "") for trade in trades if "QUARANTINED" in str(trade.get("status", "")).upper()}
    rows = [_row(trade, quarantined_ids) for trade in closed]
    pnl_issue_ids = [row["trade_id"] for row in rows if row["pnl_integrity_status"] != "PNL_INTEGRITY_OK"]
    invalid_risk_ids = [row["trade_id"] for row in rows if not row["risk_distance_valid"]]
    quarantine_ids = [row["trade_id"] for row in rows if row["was_quarantined"] or row["invalid_close"]]
    total_scaled = round(sum(float(row["scaled_pnl"] or 0.0) for row in rows), 10)
    total_raw = round(sum(float(row["raw_pnl"] or 0.0) for row in rows), 10)
    status = "PNL_INTEGRITY_ISSUE" if pnl_issue_ids or invalid_risk_ids else "PNL_INTEGRITY_OK"
    return {
        "closed_trade_attribution_status": "CLOSED_TRADE_ATTRIBUTION_OK" if status == "PNL_INTEGRITY_OK" and not quarantine_ids else "CLOSED_TRADE_ATTRIBUTION_REVIEW",
        "pnl_integrity_status": status,
        "closed_trade_count": len(rows),
        "closed_trade_ids": [row["trade_id"] for row in rows],
        "closed_scaled_pnl_total": total_scaled,
        "closed_raw_pnl_total": total_raw,
        "closed_loss_legitimate": bool(rows) and total_scaled < 0 and not pnl_issue_ids and not invalid_risk_ids and not quarantine_ids,
        "pnl_integrity_issue_trade_ids": pnl_issue_ids,
        "invalid_risk_distance_trade_ids": invalid_risk_ids,
        "quarantined_or_invalid_close_closed_trade_ids": quarantine_ids,
        "closed_trade_rows": rows,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _row(trade: Mapping[str, Any], quarantined_ids: set[str]) -> dict[str, Any]:
    trade_id = str(trade.get("paper_trade_id") or "")
    entry = _float(trade.get("entry_price"))
    exit_price = _float(trade.get("exit_price"))
    sl = _float(trade.get("sl_price"))
    tp = _float(trade.get("tp_price"))
    direction = str(trade.get("direction") or trade.get("side") or "").upper()
    raw = _float(trade.get("raw_pnl", trade.get("profit"))) or 0.0
    scaled = _float(trade.get("scaled_paper_pnl", trade.get("profit"))) or 0.0
    risk_distance = abs(entry - sl) if entry is not None and sl is not None else None
    reward_distance = abs(tp - entry) if entry is not None and tp is not None else None
    metadata = trade.get("metadata") if isinstance(trade.get("metadata"), Mapping) else {}
    extras = metadata.get("paper_trade_extra_fields") if isinstance(metadata.get("paper_trade_extra_fields"), Mapping) else {}
    invalid_close = bool(trade.get("invalid_close") or metadata.get("invalid_close") or extras.get("invalid_close"))
    multiplier = _float(trade.get("paper_risk_multiplier")) or _float(metadata.get("paper_risk_multiplier")) or 1.0
    expected_scaled = raw * multiplier
    tolerance = max(1e-6, abs(raw) * 0.0001)
    pnl_ok = abs(expected_scaled - scaled) <= tolerance or abs(multiplier - 1.0) <= 1e-12 and abs(raw - scaled) <= tolerance
    close_reason = str(trade.get("exit_reason") or "")
    return {
        "trade_id": trade_id,
        "symbol": str(trade.get("symbol") or ""),
        "side": direction,
        "entry_price": entry,
        "close_price": exit_price,
        "sl_price": sl,
        "tp_price": tp,
        "opened_at": str(trade.get("opened_at_utc") or trade.get("entry_time_utc") or ""),
        "closed_at": str(trade.get("closed_at_utc") or trade.get("exit_time_utc") or ""),
        "close_reason": close_reason,
        "raw_pnl": raw,
        "scaled_pnl": scaled,
        "paper_risk_multiplier": multiplier,
        "risk_distance": risk_distance,
        "reward_distance": reward_distance,
        "risk_distance_valid": risk_distance is not None and risk_distance > 1e-12,
        "counted_in_daily_drawdown": True,
        "was_quarantined": trade_id in quarantined_ids or "QUARANTINED" in str(trade.get("status", "")).upper(),
        "invalid_close": invalid_close,
        "normal_paper_exit": bool(close_reason and exit_price is not None and str(trade.get("status", "")).upper() == "CLOSED" and not invalid_close),
        "came_from_manage_open_trades_only": bool(metadata.get("paper_resume_mode") == "MANAGE_OPEN_TRADES_ONLY" or metadata.get("open_trade_integrity_repair")),
        "pnl_integrity_status": "PNL_INTEGRITY_OK" if pnl_ok else "PNL_INTEGRITY_ISSUE",
    }


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None
