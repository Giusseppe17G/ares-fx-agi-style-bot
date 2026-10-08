"""Spread model for current, historical and broker-profile costs."""

from __future__ import annotations

import csv
import json
import math
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
    reject_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpreadModel:
    """Resolve conservative spread assumptions from available data."""

    def __init__(self, *, max_spread_points: float = 25.0, broker_cost_profile: Mapping[str, Any] | None = None) -> None:
        self.max_spread_points = _spread_value(max_spread_points)
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
        try:
            current = _spread_value(snapshot.spread_points) if snapshot is not None else None
            profile = self._profile_for(symbol)
            observed = [_spread_value(item) for item in forward_spreads]
            if historical_csv is not None:
                observed.extend(_csv_spreads(historical_csv))
            # Validate all supplied statistics, even when a higher-priority alias
            # exists. Corrupt evidence must not be hidden by a fallback.
            stats = {
                name: _spread_value(profile[name])
                for name in ("spread_p95", "p95_spread", "spread_p99", "p99_spread", "spread_median", "median_spread")
                if profile.get(name) is not None
            }
        except (ValueError, TypeError, OSError, UnicodeError):
            return self._blocked("SPREAD_DATA_INVALID")
        if current is None and not observed and not any(name in stats for name in ("spread_p95", "p95_spread")):
            # A median (or a p99 alone) is not the required p95 fallback.
            # Using the configured limit here would manufacture permissive data.
            return self._blocked("SPREAD_DATA_MISSING")
        p95 = _first_present(stats.get("spread_p95"), stats.get("p95_spread"), _percentile(observed, 95), current, self.max_spread_points)
        p99 = _first_present(stats.get("spread_p99"), stats.get("p99_spread"), _percentile(observed, 99), p95)
        expected = _first_present(stats.get("spread_median"), stats.get("median_spread"), median(observed) if observed else None, current, p95)
        effective = current if current is not None else p95
        regime = "NORMAL"
        if effective > self.max_spread_points:
            regime = "EXTREME"
        elif (effective > 0 and effective >= self.max_spread_points * 0.75) or (p95 > 0 and p95 >= self.max_spread_points):
            regime = "ELEVATED"
        return SpreadEstimate(
            current_spread=current,
            expected_spread=expected,
            p95_spread=p95,
            p99_spread=p99,
            spread_regime=regime,
            trade_allowed_by_spread=effective <= self.max_spread_points,
            source="tick" if current is not None else ("profile" if stats else "observed"),
            execution_attempted=False,
            reject_reason="SPREAD_EXTREME" if regime == "EXTREME" else "",
        )

    def _blocked(self, reason: str) -> SpreadEstimate:
        # Finite placeholders keep the rejected audit record strict-JSON safe.
        return SpreadEstimate(
            current_spread=None, expected_spread=self.max_spread_points,
            p95_spread=self.max_spread_points, p99_spread=self.max_spread_points,
            spread_regime="INVALID", trade_allowed_by_spread=False,
            source="unavailable", reject_reason=reason,
        )

    def _profile_for(self, symbol: str) -> dict[str, Any]:
        for name in ("symbols", "by_symbol"):
            symbols = self.profile.get(name)
            if symbols is None:
                continue
            if not isinstance(symbols, Mapping):
                raise ValueError("spread profile container must be a mapping")
            if symbol.upper() in symbols:
                values = symbols[symbol.upper()]
                if not isinstance(values, Mapping):
                    raise ValueError("symbol spread profile must be a mapping")
                return dict(values)
        if str(self.profile.get("symbol", "")).upper() == symbol.upper():
            return self.profile
        return {}


def _csv_spreads(path: str | Path) -> list[float]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "spread" not in (reader.fieldnames or []):
            raise ValueError("historical spread column is missing")
        return [_spread_value(row["spread"]) for row in reader]


def _spread_value(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("spread must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("spread must be finite and non-negative")
    return number


def _first_present(*values: float | None) -> float:
    return next(value for value in values if value is not None)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100.0) * (len(ordered) - 1))))
    return ordered[index]

