"""Spread model for current, historical and broker-profile costs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from agi_style_forex_bot_mt5.contracts import MarketSnapshot


@dataclass(frozen=True)
class SpreadEstimate:
    current_spread: float | None
    expected_spread: float
    p95_spread: float
    p99_spread: float
    spread_regime: str
    trade_allowed_by_spread: bool
    source: str
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpreadModel:
    """Resolve conservative spread assumptions from available data."""

    def __init__(self, *, max_spread_points: float = 25.0, broker_cost_profile: Mapping[str, Any] | None = None) -> None:
        self.max_spread_points = max_spread_points
        self.profile = dict(broker_cost_profile or {})

    @classmethod
    def from_profile_path(cls, path: str | Path | None, *, max_spread_points: float = 25.0) -> "SpreadModel":
        if path is None or not Path(path).exists():
            return cls(max_spread_points=max_spread_points)
        return cls(max_spread_points=max_spread_points, broker_cost_profile=json.loads(Path(path).read_text(encoding="utf-8")))

    def estimate(
        self,
        *,
        symbol: str,
        snapshot: MarketSnapshot | None = None,
        forward_spreads: Iterable[float] = (),
        historical_csv: str | Path | None = None,
    ) -> SpreadEstimate:
        current = float(snapshot.spread_points) if snapshot is not None else None
        profile = self._profile_for(symbol)
        observed = [float(item) for item in forward_spreads if float(item) >= 0]
        if historical_csv is not None and Path(historical_csv).exists():
            observed.extend(_csv_spreads(historical_csv))
        p95 = float(profile.get("spread_p95") or profile.get("p95_spread") or _percentile(observed, 95) or current or self.max_spread_points)
        p99 = float(profile.get("spread_p99") or profile.get("p99_spread") or _percentile(observed, 99) or p95)
        expected = float(profile.get("spread_median") or profile.get("median_spread") or (median(observed) if observed else current or p95))
        regime = "NORMAL"
        if (current or expected) >= self.max_spread_points:
            regime = "EXTREME"
        elif (current or expected) >= self.max_spread_points * 0.75 or p95 >= self.max_spread_points:
            regime = "ELEVATED"
        return SpreadEstimate(
            current_spread=current,
            expected_spread=expected,
            p95_spread=p95,
            p99_spread=p99,
            spread_regime=regime,
            trade_allowed_by_spread=(current if current is not None else p95) <= self.max_spread_points,
            source="tick" if current is not None else ("profile" if profile else "fallback"),
            execution_attempted=False,
        )

    def _profile_for(self, symbol: str) -> dict[str, Any]:
        symbols = self.profile.get("symbols") if isinstance(self.profile.get("symbols"), Mapping) else {}
        if isinstance(symbols, Mapping):
            return dict(symbols.get(symbol.upper()) or {})
        by_symbol = self.profile.get("by_symbol") if isinstance(self.profile.get("by_symbol"), Mapping) else {}
        if isinstance(by_symbol, Mapping):
            return dict(by_symbol.get(symbol.upper()) or {})
        if str(self.profile.get("symbol", "")).upper() == symbol.upper():
            return self.profile
        return {}


def _csv_spreads(path: str | Path) -> list[float]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "spread" not in (reader.fieldnames or []):
            return []
        return [float(row["spread"]) for row in reader if row.get("spread") not in {None, ""}]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100.0) * (len(ordered) - 1))))
    return ordered[index]

