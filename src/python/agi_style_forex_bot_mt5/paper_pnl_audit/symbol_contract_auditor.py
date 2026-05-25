"""Symbol contract metadata audit for paper PnL formulas."""

from __future__ import annotations

from typing import Any, Mapping


DEFAULTS = {
    "JPY": {"digits": 3, "point": 0.001, "tick_size": 0.001, "tick_value": 1.0, "contract_size": 100000.0},
    "FOREX": {"digits": 5, "point": 0.00001, "tick_size": 0.00001, "tick_value": 1.0, "contract_size": 100000.0},
}


def audit_symbol_contracts(trades: list[Mapping[str, Any]], mt5_client: Any | None = None) -> list[dict[str, Any]]:
    symbols = sorted({str(trade.get("symbol") or "").upper() for trade in trades if trade.get("symbol")})
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        info = _mt5_info(symbol, mt5_client)
        fallback = _fallback(symbol)
        rows.append(
            {
                "symbol": symbol,
                "contract_status": "OK" if info else "SYMBOL_CONTRACT_INFO_UNAVAILABLE",
                "digits": info.get("digits", fallback["digits"]),
                "point": info.get("point", fallback["point"]),
                "tick_size": info.get("trade_tick_size", info.get("tick_size", fallback["tick_size"])),
                "tick_value": info.get("trade_tick_value", info.get("tick_value", fallback["tick_value"])),
                "contract_size": info.get("trade_contract_size", fallback["contract_size"]),
                "spread": info.get("spread", 0.0),
                "volume_min": info.get("volume_min", 0.0),
                "volume_step": info.get("volume_step", 0.0),
                "execution_attempted": False,
            }
        )
    return rows


def contract_for(symbol: str, contract_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    for row in contract_rows:
        if str(row.get("symbol", "")).upper() == symbol.upper():
            return dict(row)
    return {"symbol": symbol.upper(), **_fallback(symbol)}


def _mt5_info(symbol: str, mt5_client: Any | None) -> dict[str, Any]:
    if mt5_client is None:
        return {}
    getter = getattr(mt5_client, "symbol_info", None)
    if not callable(getter):
        return {}
    raw = getter(symbol)
    if raw is None:
        return {}
    if hasattr(raw, "_asdict"):
        return dict(raw._asdict())
    try:
        return dict(raw)
    except Exception:
        return {name: getattr(raw, name) for name in dir(raw) if not name.startswith("_") and isinstance(getattr(raw, name), (int, float, str, bool))}


def _fallback(symbol: str) -> dict[str, float | int]:
    return dict(DEFAULTS["JPY" if "JPY" in symbol.upper() else "FOREX"])
