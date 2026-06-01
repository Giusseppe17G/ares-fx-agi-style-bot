"""Exposure guard explainability for Micro V2 consolidated audit."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


EXPOSURE_KEYS = ("current_exposure", "open_risk_pct", "portfolio_heat", "exposure_pct", "correlation_exposure", "pending_exposure")
LIMIT_KEYS = ("MAX_OPEN_RISK_PCT", "MAX_PORTFOLIO_HEAT", "MAX_EXPOSURE_PCT", "MAX_CORRELATION_EXPOSURE")


def audit_exposure_explainability(dataset: Mapping[str, Any], checkpoint: Mapping[str, Any], profile_values: Mapping[str, str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    symbol_counts: Counter[str] = Counter()
    session_counts: Counter[str] = Counter()
    for event in dataset.get("events", []):
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        if str(event.get("event_type", "")).upper() != "RISK_REJECTED":
            continue
        text = _reason_text(event, payload)
        if not _is_exposure(text):
            continue
        symbol = str(event.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "UNKNOWN").upper()
        session = str(payload.get("session") or payload.get("market_session") or payload.get("session_name") or "UNKNOWN").upper()
        actual = _first_number(payload, EXPOSURE_KEYS)
        limit = _first_number(payload, ("exposure_limit", "max_open_risk_pct", "portfolio_heat_limit", "limit"))
        rows.append(
            {
                "timestamp_utc": event.get("timestamp_utc", ""),
                "symbol": symbol,
                "session": session,
                "exposure_subreason": text,
                "actual_exposure": actual,
                "exposure_limit": limit,
                "paper_trades_open_at_checkpoint": int(checkpoint.get("v2_paper_trades_open", 0) or 0),
                "source": event.get("source", ""),
                "execution_attempted": False,
                "order_send_called": False,
                "order_check_called": False,
            }
        )
        symbol_counts[symbol] += 1
        session_counts[session] += 1
    parse_errors = _profile_parse_errors(profile_values)
    data_missing = bool(rows) and all(row.get("actual_exposure") in ("", None) for row in rows)
    exposure_zero = bool(rows) and not data_missing and all(float(row.get("actual_exposure") or 0.0) == 0.0 for row in rows)
    paper_open = int(checkpoint.get("v2_paper_trades_open", 0) or 0)
    return {
        "exposure_block_count": len(rows),
        "exposure_blocks": rows,
        "exposure_by_symbol": [{"symbol": symbol, "count": count, "execution_attempted": False, "order_send_called": False, "order_check_called": False} for symbol, count in symbol_counts.most_common()],
        "exposure_by_session": [{"session": session, "count": count, "execution_attempted": False, "order_send_called": False, "order_check_called": False} for session, count in session_counts.most_common()],
        "paper_trades_open": paper_open,
        "exposure_actual_zero": exposure_zero,
        "exposure_data_missing": data_missing,
        "profile_parse_errors": parse_errors,
        "profile_parse_error": bool(parse_errors),
        "exposure_guard_diagnosis": _diagnosis(rows, paper_open, exposure_zero, data_missing, parse_errors),
        "affected_symbols": [symbol for symbol, _count in symbol_counts.most_common()],
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _diagnosis(rows: list[Mapping[str, Any]], paper_open: int, exposure_zero: bool, data_missing: bool, parse_errors: list[str]) -> str:
    if parse_errors:
        return "EXPOSURE_PROFILE_PARSE_ERROR"
    if data_missing:
        return "EXPOSURE_DATA_MISSING"
    if rows and paper_open == 0 and exposure_zero:
        return "EXPOSURE_POSSIBLE_DOUBLE_COUNTING"
    if rows:
        return "EXPOSURE_GUARD_EXPECTED"
    return "NO_EXPOSURE_BLOCKS"


def _reason_text(event: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    reasons = payload.get("blocking_reasons")
    if isinstance(reasons, list) and reasons:
        return " ".join(str(item) for item in reasons).upper()
    return str(payload.get("reason") or payload.get("risk_reason") or payload.get("blocking_reason") or event.get("message") or "").upper()


def _is_exposure(text: str) -> bool:
    return any(token in text.upper() for token in ("EXPOSURE", "CORRELATION", "OPEN_RISK", "PORTFOLIO_HEAT"))


def _first_number(payload: Mapping[str, Any], keys: tuple[str, ...]) -> float | str:
    for key in keys:
        for candidate in (key, key.upper(), key.lower()):
            if candidate in payload:
                try:
                    return float(payload[candidate])
                except Exception:
                    return ""
    return ""


def _profile_parse_errors(values: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    for key in LIMIT_KEYS:
        if key not in values:
            continue
        try:
            float(values[key])
        except Exception:
            errors.append(key)
    return errors
