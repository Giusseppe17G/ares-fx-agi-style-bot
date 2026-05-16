"""Currency exposure calculations for Forex pairs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CurrencyExposure:
    net: dict[str, float]
    gross: dict[str, float]
    limits: dict[str, float]
    breaches: dict[str, float]
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_currency_exposure(
    trades: Iterable[Mapping[str, Any] | Any],
    *,
    max_currency_exposure_pct: float = 2.0,
    max_usd_exposure_pct: float = 3.0,
) -> CurrencyExposure:
    net: dict[str, float] = {}
    gross: dict[str, float] = {}
    for trade in trades:
        symbol = str(_get(trade, "symbol") or _get(trade, "broker_symbol") or "").upper()
        if len(symbol) < 6:
            continue
        base, quote = symbol[:3], symbol[3:6]
        direction = str(_get(trade, "direction") or _get(trade, "side") or "").upper()
        risk = float(_get(trade, "risk_pct") or _get(trade, "risk_amount_pct") or _get(trade, "risk") or 0.0)
        if risk <= 0:
            risk = float(_get(trade, "lot") or 0.0) * 0.1
        base_sign = 1.0 if direction == "BUY" else -1.0
        quote_sign = -base_sign
        _add(net, base, base_sign * risk)
        _add(net, quote, quote_sign * risk)
        _add(gross, base, abs(risk))
        _add(gross, quote, abs(risk))
    limits = {currency: (max_usd_exposure_pct if currency == "USD" else max_currency_exposure_pct) for currency in set(net) | set(gross)}
    breaches = {currency: value for currency, value in gross.items() if value > limits.get(currency, max_currency_exposure_pct)}
    return CurrencyExposure(net=net, gross=gross, limits=limits, breaches=breaches, execution_attempted=False)


def projected_trade_exposure(signal: Any, risk_pct: float) -> dict[str, float]:
    symbol = str(getattr(signal, "symbol", "")).upper()
    direction = str(getattr(getattr(signal, "direction", ""), "value", getattr(signal, "direction", ""))).upper()
    if len(symbol) < 6:
        return {}
    base, quote = symbol[:3], symbol[3:6]
    sign = 1.0 if direction == "BUY" else -1.0
    return {base: sign * risk_pct, quote: -sign * risk_pct}


def _add(target: dict[str, float], key: str, value: float) -> None:
    target[key] = target.get(key, 0.0) + value


def _get(value: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)
