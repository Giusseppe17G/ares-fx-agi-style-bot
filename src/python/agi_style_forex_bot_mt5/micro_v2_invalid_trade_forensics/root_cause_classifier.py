"""Root cause classification for invalid V2 paper trades."""

from __future__ import annotations

from typing import Any, Mapping


DETERMINISTIC_ROOT_CAUSES = {
    "SL_EQUALS_ENTRY",
    "TP_EQUALS_ENTRY",
    "SL_MISSING",
    "TP_MISSING",
    "SL_WRONG_SIDE_FOR_LONG",
    "SL_WRONG_SIDE_FOR_SHORT",
    "TP_WRONG_SIDE_FOR_LONG",
    "TP_WRONG_SIDE_FOR_SHORT",
    "ZERO_ATR_OR_ZERO_STOP_DISTANCE",
    "NEGATIVE_RISK_DISTANCE",
    "SYMBOL_PRECISION_ROUNDING_COLLAPSE",
    "PRICE_DATA_MISSING_AT_ENTRY",
    "SIGNAL_WITH_INVALID_STOP",
    "FALLBACK_STOP_NOT_APPLIED",
    "SERIALIZATION_OR_SCHEMA_ISSUE",
}


def classify_root_cause(
    trades: list[Mapping[str, Any]],
    risk: Mapping[str, Any],
    sl_tp: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    if not trades:
        cause = "NO_INVALID_TRADES"
    else:
        row = dict(trades[0])
        sl_row = (sl_tp.get("sl_tp_forensics") or [{}])[0]
        risk_row = (risk.get("risk_distance_forensics") or [{}])[0]
        cause = _classify_one(row, risk_row, sl_row, inputs)
    return {
        "root_cause": cause,
        "root_cause_deterministic": cause in DETERMINISTIC_ROOT_CAUSES,
        "root_cause_evidence": _evidence(trades[0] if trades else {}, risk, sl_tp),
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _classify_one(row: Mapping[str, Any], risk_row: Mapping[str, Any], sl_row: Mapping[str, Any], inputs: Mapping[str, Any]) -> str:
    if sl_row.get("sl_missing"):
        return "SL_MISSING"
    if sl_row.get("tp_missing"):
        return "TP_MISSING"
    if sl_row.get("sl_equals_entry"):
        if risk_row.get("precision_rounding_possible"):
            return "SYMBOL_PRECISION_ROUNDING_COLLAPSE"
        if _zero_stop_context(row, inputs):
            return "ZERO_ATR_OR_ZERO_STOP_DISTANCE"
        return "SL_EQUALS_ENTRY"
    if sl_row.get("tp_equals_entry"):
        return "TP_EQUALS_ENTRY"
    for key, cause in (
        ("sl_wrong_side_for_long", "SL_WRONG_SIDE_FOR_LONG"),
        ("sl_wrong_side_for_short", "SL_WRONG_SIDE_FOR_SHORT"),
        ("tp_wrong_side_for_long", "TP_WRONG_SIDE_FOR_LONG"),
        ("tp_wrong_side_for_short", "TP_WRONG_SIDE_FOR_SHORT"),
    ):
        if sl_row.get(key):
            return cause
    if risk_row.get("negative_risk_distance"):
        return "NEGATIVE_RISK_DISTANCE"
    if row.get("missing_current_price"):
        return "PRICE_DATA_MISSING_AT_ENTRY"
    return "UNKNOWN_REQUIRES_MANUAL_REVIEW"


def _zero_stop_context(row: Mapping[str, Any], inputs: Mapping[str, Any]) -> bool:
    for key in ("atr", "atr14", "stop_distance", "raw_stop_distance"):
        value = row.get(key)
        if value in {0, 0.0, "0", "0.0"}:
            return True
    payload_text = ""
    for event in inputs.get("v2_dataset", {}).get("events", []):
        payload_text += " " + str(event.get("payload", {})).upper()
    return ("'ATR': 0" in payload_text or '"ATR": 0' in payload_text or "STOP_DISTANCE': 0" in payload_text or '"STOP_DISTANCE": 0' in payload_text)


def _evidence(row: Mapping[str, Any], risk: Mapping[str, Any], sl_tp: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trade_id": row.get("trade_id") or row.get("paper_trade_id") or "",
        "symbol": row.get("symbol", ""),
        "side": row.get("side", ""),
        "entry_price": row.get("entry_price"),
        "sl_price": row.get("sl_price"),
        "tp_price": row.get("tp_price"),
        "risk_distance_issue_count": risk.get("risk_distance_issue_count", 0),
        "sl_tp_issue_count": sl_tp.get("sl_tp_issue_count", 0),
    }
