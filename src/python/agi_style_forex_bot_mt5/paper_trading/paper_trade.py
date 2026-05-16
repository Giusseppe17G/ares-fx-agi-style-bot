"""Paper trade lifecycle contract."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping
from uuid import uuid4


@dataclass(frozen=True)
class PaperTrade:
    paper_trade_id: str
    signal_id: str
    idempotency_key: str
    symbol: str
    broker_symbol: str
    direction: str
    entry_time_utc: str
    entry_price: float
    sl_price: float
    tp_price: float
    lot: float
    risk_pct: float
    risk_amount: float
    strategy_name: str
    strategy_version: str
    regime: str
    session: str
    score: float
    reasons: tuple[str, ...]
    status: str = "OPEN"
    exit_time_utc: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    profit: float = 0.0
    r_multiple: float = 0.0
    mae: float = 0.0
    mfe: float = 0.0
    spread_at_entry: float = 0.0
    spread_at_exit: float = 0.0
    slippage_assumed_points: float = 0.0
    commission_assumed: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @staticmethod
    def new_id() -> str:
        return f"ptr_{uuid4().hex}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True)

    @staticmethod
    def from_json(payload: str) -> "PaperTrade":
        data = json.loads(payload)
        if isinstance(data.get("reasons"), list):
            data["reasons"] = tuple(data["reasons"])
        return PaperTrade(**data)

    @staticmethod
    def from_mapping(payload: Mapping[str, Any]) -> "PaperTrade":
        data = dict(payload)
        if isinstance(data.get("reasons"), list):
            data["reasons"] = tuple(data["reasons"])
        return PaperTrade(**data)

    def replace(self, **updates: Any) -> "PaperTrade":
        data = self.to_dict()
        data.update(updates)
        if isinstance(data.get("reasons"), list):
            data["reasons"] = tuple(data["reasons"])
        return PaperTrade(**data)
