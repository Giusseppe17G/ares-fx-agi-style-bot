"""Central paper PnL scaling for paper/shadow trades."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


PNL_FORMULA_VERSION = "paper_pnl_scaled_v1"


def calculate_raw_pnl(trade: Mapping[str, Any], symbol_contract: Mapping[str, Any] | None = None) -> float:
    """Return unscaled paper PnL from price movement and symbol contract assumptions."""

    contract = symbol_contract or {}
    entry = _float(trade.get("entry_price"))
    exit_price = _float(trade.get("exit_price") or trade.get("current_price"))
    direction = str(trade.get("direction") or "").upper()
    lot = _float(trade.get("lot") or trade.get("volume") or trade.get("paper_size"))
    tick_size = max(_float(contract.get("tick_size") or contract.get("trade_tick_size") or trade.get("tick_size"), _fallback_tick_size(str(trade.get("symbol", "")))), 1e-12)
    tick_value = _float(contract.get("tick_value") or contract.get("trade_tick_value") or trade.get("tick_value"), 1.0)
    commission = _float(trade.get("commission_assumed"))
    move = exit_price - entry
    if direction == "SELL":
        move *= -1.0
    return (move / tick_size) * tick_value * lot - commission


def apply_paper_risk_multiplier(raw_pnl: float, multiplier: float) -> float:
    """Apply a bounded paper risk multiplier to raw paper PnL."""

    return float(raw_pnl) * max(0.0, min(1.0, _float(multiplier, 1.0)))


def calculate_scaled_paper_pnl(
    trade: Mapping[str, Any],
    profile_config: str | Path | None = None,
    symbol_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return raw/scaled paper PnL plus audit metadata."""

    raw = calculate_raw_pnl(trade, symbol_contract=symbol_contract)
    profile_multiplier = extract_paper_risk_multiplier(profile_config)
    metadata = trade.get("metadata") if isinstance(trade.get("metadata"), Mapping) else {}
    paper_multiplier = _first_float(
        metadata.get("paper_risk_multiplier"),
        trade.get("paper_risk_multiplier"),
        profile_multiplier,
        default=1.0,
    )
    risk_multiplier = _first_float(
        metadata.get("risk_multiplier"),
        (metadata.get("dynamic_risk") if isinstance(metadata.get("dynamic_risk"), Mapping) else {}).get("risk_multiplier"),
        trade.get("risk_multiplier"),
        default=1.0,
    )
    combined = max(0.0, min(1.0, paper_multiplier)) * max(0.0, min(1.0, risk_multiplier))
    scaled = apply_paper_risk_multiplier(raw, combined)
    warnings = validate_pnl_units(trade, symbol_contract=symbol_contract)
    if profile_config and profile_multiplier is None:
        warnings.append("PAPER_RISK_MULTIPLIER_MISSING")
    return {
        "raw_pnl": raw,
        "scaled_pnl": scaled,
        "scaled_paper_pnl": scaled,
        "paper_risk_multiplier": paper_multiplier,
        "risk_multiplier": risk_multiplier,
        "combined_pnl_multiplier": combined,
        "multiplier_applied": combined < 1.0,
        "pnl_formula_version": PNL_FORMULA_VERSION,
        "pnl_scaling_status": "SCALED_PAPER_PNL" if combined < 1.0 else "UNSCALED_MULTIPLIER_1",
        "warnings": warnings,
    }


def extract_paper_risk_multiplier(profile_config: str | Path | None) -> float | None:
    """Read PAPER_RISK_MULTIPLIER from a simple INI overlay, accepting case variants."""

    if profile_config is None:
        return None
    path = Path(profile_config)
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized = key.strip().lower()
        if normalized in {"paper_risk_multiplier", "paper-risk-multiplier"}:
            return _float(value, 1.0)
    return None


def validate_pnl_units(trade: Mapping[str, Any], symbol_contract: Mapping[str, Any] | None = None) -> list[str]:
    """Return warnings for obviously suspicious paper PnL units."""

    warnings: list[str] = []
    contract = symbol_contract or {}
    entry = _float(trade.get("entry_price"))
    exit_price = _float(trade.get("exit_price") or trade.get("current_price"))
    point = max(_float(contract.get("point") or trade.get("point"), _fallback_tick_size(str(trade.get("symbol", "")))), 1e-12)
    if entry and exit_price and abs(exit_price - entry) / point > 5000:
        warnings.append("POINT_PIP_MISMATCH_POSSIBLE")
    if _float(trade.get("lot") or trade.get("volume")) <= 0:
        warnings.append("PAPER_LOT_MISSING_OR_ZERO")
    return warnings


def pnl_value(trade: Mapping[str, Any]) -> float:
    """Return the scaled PnL basis used for paper risk and drawdown."""

    return _float(trade.get("scaled_paper_pnl"), _float(trade.get("profit")))


def pnl_basis(trade: Mapping[str, Any]) -> str:
    """Return whether a trade is scaled or legacy unscaled."""

    if "scaled_paper_pnl" in trade or "raw_pnl" in trade:
        return "SCALED_PAPER_PNL"
    return "LEGACY_UNSCALED_PNL"


def _fallback_tick_size(symbol: str) -> float:
    return 0.001 if "JPY" in symbol.upper() else 0.00001


def _first_float(*values: Any, default: float) -> float:
    for value in values:
        if value is None or value == "":
            continue
        return _float(value, default)
    return float(default)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
