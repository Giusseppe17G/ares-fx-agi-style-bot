"""Deterministic price alignment to the broker's executable tick lattice."""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext
from math import isfinite, ulp


def _decimal(value: float | Decimal, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} must be numeric")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError(f"{name} must be finite")
    return number


def is_price_on_tick_grid(price: float, tick_size: float) -> bool:
    """Require an observed positive executable price without modifying it."""
    try:
        value, tick = _decimal(price, "price"), _decimal(tick_size, "tick_size")
        return value > 0 and tick > 0 and value % tick == 0
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return False


def snap_price_to_tick(price: float | Decimal, tick_size: float, *, rounding: str) -> float:
    """Align a positive price up/down; never infer a grid from display digits."""
    price_value = _decimal(price, "price")
    tick = _decimal(tick_size, "tick_size")
    if price_value <= 0 or tick <= 0 or rounding not in {"up", "down"}:
        raise ValueError("positive price, tick size and explicit rounding are required")
    with localcontext() as context:
        context.prec = 80
        steps = (price_value / tick).to_integral_value(rounding=ROUND_CEILING if rounding == "up" else ROUND_FLOOR)
        aligned = steps * tick
    result = float(aligned)
    if not isfinite(result) or result <= 0 or Decimal(str(result)) != aligned:
        raise ValueError("aligned price cannot be represented safely")
    return result


def adverse_fill_price(*, base_price: float, point: float, slippage_points: float,
                       tick_size: float, direction: str, is_entry: bool) -> float:
    """Round executions against the position after applying adverse slippage."""
    if direction not in {"BUY", "SELL"} or not isinstance(is_entry, bool):
        raise ValueError("direction and execution stage are required")
    base = _decimal(base_price, "base_price")
    point_value = _decimal(point, "point")
    slip = _decimal(slippage_points, "slippage_points")
    if point_value <= 0 or slip < 0:
        raise ValueError("point must be positive and slippage non-negative")
    upward = (direction == "BUY") == is_entry
    with localcontext() as context:
        context.prec = 80
        # Synthesised asks such as bid + spread * point can carry a final binary
        # ULP. Remove only that representation noise, never a material point
        # fraction; otherwise an integral slip gains an unintended extra tick.
        nearest_point = (base / point_value).to_integral_value() * point_value
        tolerance = min(point_value * Decimal("1e-9"), Decimal(str(ulp(float(base)))) * 2)
        if abs(base - nearest_point) <= tolerance:
            base = nearest_point
        price = base + (point_value * slip if upward else -point_value * slip)
    return snap_price_to_tick(price, tick_size, rounding="up" if upward else "down")
