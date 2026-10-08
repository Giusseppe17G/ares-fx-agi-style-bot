"""Baselines a candidate strategy must beat before it counts as an edge.

A higher win rate is not evidence. These three baselines make the null
hypotheses explicit and runnable:

* buy and hold      -- would simply holding the instrument have done as well?
* random entry      -- does entry timing carry information, or is the result
                       explained by exposure alone?
* permuted signal   -- keep the signals, shuffle which bar they land on. If the
                       permuted version scores as well, the edge is in the
                       market's drift, not in the signal.

All three are seeded and therefore reproducible: the same seed gives the same
baseline, so a comparison can be repeated exactly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..safety import SafetyEnvelope


@dataclass(frozen=True)
class BaselineResult:
    baseline_id: str
    trades: int
    net_return: float
    win_rate: float
    seed: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "trades": self.trades,
            "net_return": round(self.net_return, 8),
            "win_rate": round(self.win_rate, 6),
            "seed": self.seed,
        }


def buy_and_hold(closes: Sequence[float]) -> BaselineResult:
    if len(closes) < 2:
        return BaselineResult("buy_and_hold", 0, 0.0, 0.0)
    net = float(closes[-1]) - float(closes[0])
    return BaselineResult("buy_and_hold", 1, net, 1.0 if net > 0 else 0.0)


def random_entry(closes: Sequence[float], *, trades: int, holding_bars: int = 12, seed: int = 82) -> BaselineResult:
    """Enter at random bars, hold a fixed number of bars. Exposure without timing."""

    if len(closes) <= holding_bars or trades <= 0:
        return BaselineResult("random_entry", 0, 0.0, 0.0, seed=seed)
    rng = random.Random(seed)
    returns: list[float] = []
    for _ in range(trades):
        start = rng.randrange(0, len(closes) - holding_bars)
        returns.append(float(closes[start + holding_bars]) - float(closes[start]))
    return _from_returns("random_entry", returns, seed=seed)


def permuted_signal(closes: Sequence[float], signal_bars: Sequence[int], *, holding_bars: int = 12, seed: int = 82) -> BaselineResult:
    """Keep the number of signals, move them to random bars. Destroys timing, keeps count."""

    usable = [bar for bar in signal_bars if 0 <= bar < len(closes) - holding_bars]
    if not usable:
        return BaselineResult("permuted_signal", 0, 0.0, 0.0, seed=seed)
    rng = random.Random(seed)
    permuted = [rng.randrange(0, len(closes) - holding_bars) for _ in usable]
    returns = [float(closes[bar + holding_bars]) - float(closes[bar]) for bar in permuted]
    return _from_returns("permuted_signal", returns, seed=seed)


def compare_to_baselines(
    *,
    candidate_net_return: float,
    candidate_trades: int,
    candidate_win_rate: float,
    closes: Sequence[float],
    signal_bars: Sequence[int] = (),
    holding_bars: int = 12,
    seed: int = 82,
) -> dict[str, Any]:
    """Score a candidate against all three baselines.

    `beats_all_baselines` is a necessary condition, never a sufficient one: it
    says the candidate is not explained by drift, exposure or trade count, and
    says nothing about whether the result is out-of-sample.
    """

    baselines = [
        buy_and_hold(closes),
        random_entry(closes, trades=max(candidate_trades, 1), holding_bars=holding_bars, seed=seed),
        permuted_signal(closes, signal_bars, holding_bars=holding_bars, seed=seed),
    ]
    beaten = {baseline.baseline_id: candidate_net_return > baseline.net_return for baseline in baselines}
    payload = {
        "mode": "baseline-comparison",
        "candidate": {
            "net_return": round(float(candidate_net_return), 8),
            "trades": int(candidate_trades),
            "win_rate": round(float(candidate_win_rate), 6),
        },
        "baselines": [baseline.as_dict() for baseline in baselines],
        "beats": beaten,
        "beats_all_baselines": all(beaten.values()),
        "baseline_verdict": "CANDIDATE_BEATS_ALL_BASELINES" if all(beaten.values()) else "CANDIDATE_NOT_DISTINGUISHABLE_FROM_BASELINE",
        "note": "Beating these baselines is necessary, not sufficient: it does not establish out-of-sample validity.",
        "seed": seed,
    }
    return SafetyEnvelope().seal(payload)


def _from_returns(baseline_id: str, returns: Sequence[float], *, seed: int) -> BaselineResult:
    if not returns:
        return BaselineResult(baseline_id, 0, 0.0, 0.0, seed=seed)
    wins = sum(1 for value in returns if value > 0)
    return BaselineResult(baseline_id, len(returns), float(sum(returns)), wins / len(returns), seed=seed)
