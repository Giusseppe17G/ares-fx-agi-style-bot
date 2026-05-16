"""Gap and same-bar ambiguity handling."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class GapDecision:
    exit_price: float
    exit_reason: str
    ambiguous: bool
    flags: tuple[str, ...]
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GapModel:
    """Apply conservative gap and intrabar rules."""

    def resolve_bar_exit(self, *, direction: str, open_price: float, high: float, low: float, sl: float, tp: float, mode: str = "conservative") -> GapDecision | None:
        direction = direction.upper()
        if direction == "BUY":
            sl_hit = low <= sl
            tp_hit = high >= tp
            if open_price < sl:
                return GapDecision(open_price, "GAP_THROUGH_SL", False, ("gap_through_sl",), False)
            if sl_hit and tp_hit:
                if mode == "optimistic":
                    return GapDecision(tp, "TP", True, ("same_bar_sl_tp", "optimistic"), False)
                if mode == "intrabar_unknown":
                    return GapDecision(sl, "AMBIGUOUS", True, ("same_bar_sl_tp", "intrabar_unknown"), False)
                return GapDecision(sl, "SL", True, ("same_bar_sl_tp", "conservative"), False)
            if sl_hit:
                return GapDecision(sl, "SL", False, (), False)
            if tp_hit:
                return GapDecision(tp, "TP", False, (), False)
        else:
            sl_hit = high >= sl
            tp_hit = low <= tp
            if open_price > sl:
                return GapDecision(open_price, "GAP_THROUGH_SL", False, ("gap_through_sl",), False)
            if sl_hit and tp_hit:
                if mode == "optimistic":
                    return GapDecision(tp, "TP", True, ("same_bar_sl_tp", "optimistic"), False)
                if mode == "intrabar_unknown":
                    return GapDecision(sl, "AMBIGUOUS", True, ("same_bar_sl_tp", "intrabar_unknown"), False)
                return GapDecision(sl, "SL", True, ("same_bar_sl_tp", "conservative"), False)
            if sl_hit:
                return GapDecision(sl, "SL", False, (), False)
            if tp_hit:
                return GapDecision(tp, "TP", False, (), False)
        return None

