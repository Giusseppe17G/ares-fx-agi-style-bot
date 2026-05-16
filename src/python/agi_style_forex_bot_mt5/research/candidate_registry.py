"""Candidate registry persistence and filtering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .strategy_candidate import StrategyCandidate, candidate_fingerprint


class CandidateRegistry:
    """In-memory registry with JSON persistence and duplicate prevention."""

    def __init__(self, candidates: Iterable[StrategyCandidate] | None = None) -> None:
        self._items: dict[str, StrategyCandidate] = {}
        for candidate in candidates or ():
            self.add(candidate)

    def add(self, candidate: StrategyCandidate) -> bool:
        """Add a candidate once by candidate_id."""

        if candidate.candidate_id in self._items:
            return False
        self._items[candidate.candidate_id] = candidate
        return True

    def list(self, *, status: str | None = None) -> tuple[StrategyCandidate, ...]:
        """List candidates, optionally filtered by status."""

        items = tuple(self._items.values())
        if status is not None:
            items = tuple(item for item in items if item.status == status)
        return items

    def top(self, *, limit: int = 10) -> tuple[StrategyCandidate, ...]:
        """Return top candidates by composite score."""

        return tuple(
            sorted(
                self._items.values(),
                key=lambda item: float(item.metrics_summary.get("composite_score", 0.0) or 0.0),
                reverse=True,
            )[:limit]
        )

    def compare_versions(self, strategy_name: str, symbol: str) -> tuple[StrategyCandidate, ...]:
        """List versions for one strategy/symbol pair."""

        return tuple(
            item
            for item in self._items.values()
            if item.strategy_name == strategy_name and item.symbol == symbol.upper()
        )

    def save_json(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps([item.to_dict() for item in self._items.values()], indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def save_jsonl(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(item.to_json() for item in self._items.values()), encoding="utf-8")

    @staticmethod
    def load_json(path: str | Path) -> "CandidateRegistry":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return CandidateRegistry(StrategyCandidate(**item) for item in data)


def registry_key(candidate: StrategyCandidate) -> str:
    """Return duplicate key based on strategy/symbol/params identity."""

    return candidate_fingerprint(
        strategy_name=candidate.strategy_name,
        symbol=candidate.symbol,
        timeframe=candidate.timeframe,
        regime=candidate.regime,
        session=candidate.session,
        params=candidate.params,
    )
