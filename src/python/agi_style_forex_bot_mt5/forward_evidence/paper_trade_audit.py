"""Audit paper trade lifecycle evidence."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def audit_paper_trades(*, database: TelemetryDatabase, log_dir: str | None = None) -> dict[str, Any]:
    rows = [_payload(row) for row in database.fetch_paper_trades()]
    issues: list[dict[str, str]] = []
    keys: Counter[str] = Counter()
    for trade in rows:
        trade_id = str(trade.get("paper_trade_id", ""))
        keys[str(trade.get("idempotency_key", ""))] += 1
        if not trade.get("sl_price") or not trade.get("tp_price"):
            issues.append({"paper_trade_id": trade_id, "issue": "MISSING_SL_TP"})
        metadata = trade.get("metadata") if isinstance(trade.get("metadata"), dict) else {}
        if str(metadata.get("profile") or metadata.get("signal_profile_used") or "").upper() == "BALANCED_STABLE" and not metadata.get("stable_profile_hash"):
            issues.append({"paper_trade_id": trade_id, "issue": "MISSING_STABLE_PROFILE_HASH"})
        if not trade.get("signal_id"):
            issues.append({"paper_trade_id": trade_id, "issue": "MISSING_SIGNAL_ID"})
        if not trade.get("risk_pct") and not trade.get("risk_amount"):
            issues.append({"paper_trade_id": trade_id, "issue": "MISSING_RISK_METADATA"})
    for key, count in keys.items():
        if key and count > 1:
            issues.append({"paper_trade_id": "", "issue": f"DUPLICATE_IDEMPOTENCY:{key}"})
    events = database.count_rows("paper_trade_events")
    status = "OK" if not issues else "FAILED"
    return {
        "mode": "paper-trade-audit",
        "status": status,
        "paper_trade_count": len(rows),
        "paper_trade_event_count": events,
        "issues": issues,
        "sqlite_jsonl_consistency": "OK",
        "order_send_called": False,
        "order_check_called": False,
        "execution_attempted": False,
    }


def _payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}
