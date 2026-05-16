"""Versioned strategy research candidates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping


VALID_STATUSES = {
    "CANDIDATE",
    "WATCHLIST",
    "REJECTED",
    "APPROVED_FOR_SHADOW_OBSERVATION",
}


@dataclass(frozen=True)
class StrategyCandidate:
    """Serializable strategy candidate with reproducibility metadata."""

    candidate_id: str
    strategy_name: str
    strategy_version: str
    symbol: str
    timeframe: str
    regime: str
    session: str
    params: Mapping[str, Any]
    created_at_utc: str
    data_fingerprint: str
    cost_profile_fingerprint: str
    research_commit: str
    status: str = "CANDIDATE"
    rejection_reason: str = ""
    metrics_summary: Mapping[str, Any] = field(default_factory=dict)
    validation_artifacts: Mapping[str, Any] = field(default_factory=dict)

    @staticmethod
    def build(
        *,
        strategy_name: str,
        symbol: str,
        params: Mapping[str, Any],
        strategy_version: str = "0.1.0",
        timeframe: str = "M5",
        regime: str = "ANY",
        session: str = "ANY",
        data_fingerprint: str = "unknown",
        cost_profile_fingerprint: str = "unknown",
        research_commit: str = "unknown",
    ) -> "StrategyCandidate":
        """Create a deterministic candidate id from strategy/symbol/params."""

        fingerprint = candidate_fingerprint(
            strategy_name=strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            regime=regime,
            session=session,
            params=params,
        )
        return StrategyCandidate(
            candidate_id=f"cand_{fingerprint[:16]}",
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            regime=regime,
            session=session,
            params=dict(params),
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            data_fingerprint=data_fingerprint,
            cost_profile_fingerprint=cost_profile_fingerprint,
            research_commit=research_commit,
        )

    def with_status(
        self,
        status: str,
        *,
        rejection_reason: str = "",
        metrics_summary: Mapping[str, Any] | None = None,
        validation_artifacts: Mapping[str, Any] | None = None,
    ) -> "StrategyCandidate":
        """Return a copy with validation status fields updated."""

        if status not in VALID_STATUSES:
            raise ValueError(f"invalid candidate status: {status}")
        data = asdict(self)
        data["status"] = status
        data["rejection_reason"] = rejection_reason
        if metrics_summary is not None:
            data["metrics_summary"] = dict(metrics_summary)
        if validation_artifacts is not None:
            data["validation_artifacts"] = dict(validation_artifacts)
        return StrategyCandidate(**data)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready payload."""

        return asdict(self)

    def to_json(self) -> str:
        """Serialize as stable JSON."""

        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True)


def candidate_fingerprint(
    *,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    regime: str,
    session: str,
    params: Mapping[str, Any],
) -> str:
    """Fingerprint a candidate identity."""

    payload = {
        "strategy_name": strategy_name,
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "regime": regime,
        "session": session,
        "params": dict(sorted(params.items())),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
