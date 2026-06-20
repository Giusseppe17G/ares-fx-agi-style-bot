"""Paper trade lifecycle contract."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Mapping
from uuid import uuid4


EXTRA_FIELDS_METADATA_KEY = "paper_trade_extra_fields"


@dataclass(frozen=True, init=False)
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
    raw_pnl: float = 0.0
    scaled_paper_pnl: float = 0.0
    paper_risk_multiplier: float = 1.0
    risk_multiplier: float = 1.0
    pnl_formula_version: str = ""
    multiplier_applied: bool = False
    pnl_scaling_status: str = ""
    r_multiple: float = 0.0
    mae: float = 0.0
    mfe: float = 0.0
    spread_at_entry: float = 0.0
    spread_at_exit: float = 0.0
    slippage_assumed_points: float = 0.0
    commission_assumed: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        paper_trade_id: str,
        signal_id: str,
        idempotency_key: str,
        symbol: str,
        broker_symbol: str,
        direction: str,
        entry_time_utc: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        lot: float,
        risk_pct: float,
        risk_amount: float,
        strategy_name: str,
        strategy_version: str,
        regime: str,
        session: str,
        score: float,
        reasons: tuple[str, ...] | list[str] | None,
        status: str = "OPEN",
        exit_time_utc: str | None = None,
        exit_price: float | None = None,
        exit_reason: str | None = None,
        profit: float = 0.0,
        raw_pnl: float = 0.0,
        scaled_paper_pnl: float = 0.0,
        paper_risk_multiplier: float = 1.0,
        risk_multiplier: float = 1.0,
        pnl_formula_version: str = "",
        multiplier_applied: bool = False,
        pnl_scaling_status: str = "",
        r_multiple: float = 0.0,
        mae: float = 0.0,
        mfe: float = 0.0,
        spread_at_entry: float = 0.0,
        spread_at_exit: float = 0.0,
        slippage_assumed_points: float = 0.0,
        commission_assumed: float = 0.0,
        metadata: Mapping[str, Any] | None = None,
        **unknown_fields: Any,
    ) -> None:
        safe_metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        if unknown_fields:
            existing = safe_metadata.get(EXTRA_FIELDS_METADATA_KEY)
            merged = dict(existing) if isinstance(existing, Mapping) else {}
            merged.update({str(key): value for key, value in unknown_fields.items()})
            safe_metadata[EXTRA_FIELDS_METADATA_KEY] = merged
        normalized_reasons: tuple[str, ...]
        if reasons is None:
            normalized_reasons = tuple()
        elif isinstance(reasons, tuple):
            normalized_reasons = reasons
        else:
            normalized_reasons = tuple(str(item) for item in reasons)
        values = {
            "paper_trade_id": paper_trade_id,
            "signal_id": signal_id,
            "idempotency_key": idempotency_key,
            "symbol": symbol,
            "broker_symbol": broker_symbol,
            "direction": direction,
            "entry_time_utc": entry_time_utc,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "lot": lot,
            "risk_pct": risk_pct,
            "risk_amount": risk_amount,
            "strategy_name": strategy_name,
            "strategy_version": strategy_version,
            "regime": regime,
            "session": session,
            "score": score,
            "reasons": normalized_reasons,
            "status": status,
            "exit_time_utc": exit_time_utc,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "profit": profit,
            "raw_pnl": raw_pnl,
            "scaled_paper_pnl": scaled_paper_pnl,
            "paper_risk_multiplier": paper_risk_multiplier,
            "risk_multiplier": risk_multiplier,
            "pnl_formula_version": pnl_formula_version,
            "multiplier_applied": multiplier_applied,
            "pnl_scaling_status": pnl_scaling_status,
            "r_multiple": r_multiple,
            "mae": mae,
            "mfe": mfe,
            "spread_at_entry": spread_at_entry,
            "spread_at_exit": spread_at_exit,
            "slippage_assumed_points": slippage_assumed_points,
            "commission_assumed": commission_assumed,
            "metadata": safe_metadata,
        }
        for key, value in values.items():
            object.__setattr__(self, key, value)

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
        return PaperTrade.from_mapping(data)

    @staticmethod
    def from_mapping(payload: Mapping[str, Any]) -> "PaperTrade":
        data = _normalize_paper_trade_payload(payload)
        return PaperTrade(**data)

    def replace(self, **updates: Any) -> "PaperTrade":
        data = self.to_dict()
        data.update(updates)
        return PaperTrade.from_mapping(data)


def sanitize_paper_trade_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return constructor-safe paper-trade payload while preserving unknown fields.

    SQLite/log payloads are intentionally append-only across phases. Recovery and
    quarantine phases may add fields that older constructors do not know yet; those
    fields must not break runtime loading.
    """

    return _normalize_paper_trade_payload(payload)


def paper_trade_constructor_fields() -> set[str]:
    return {item.name for item in fields(PaperTrade)}


def paper_trade_extra_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = paper_trade_constructor_fields()
    return {str(key): value for key, value in dict(payload).items() if str(key) not in allowed}


def _normalize_paper_trade_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(payload)
    allowed = paper_trade_constructor_fields()
    data = {key: value for key, value in raw.items() if key in allowed}
    extras = {str(key): value for key, value in raw.items() if key not in allowed}
    metadata = data.get("metadata") if isinstance(data.get("metadata"), Mapping) else {}
    data["metadata"] = dict(metadata)
    if extras:
        existing = data["metadata"].get(EXTRA_FIELDS_METADATA_KEY)
        merged = dict(existing) if isinstance(existing, Mapping) else {}
        merged.update(extras)
        data["metadata"][EXTRA_FIELDS_METADATA_KEY] = merged
    if isinstance(data.get("reasons"), list):
        data["reasons"] = tuple(data["reasons"])
    elif data.get("reasons") is None:
        data["reasons"] = tuple()
    return data
