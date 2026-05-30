"""Symbol normalization checks for V2 rejection analysis."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping


FOREX_BASE_RE = re.compile(r"^[A-Z]{6}")


def normalize_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    match = FOREX_BASE_RE.match(text.replace("/", "").replace("_", ""))
    return match.group(0) if match else text


def audit_symbol_normalization(rejections: list[Mapping[str, Any]]) -> dict[str, Any]:
    raw_counter: Counter[str] = Counter()
    canonical_counter: Counter[str] = Counter()
    broker_counter: Counter[str] = Counter()
    suffix_mismatches: list[dict[str, Any]] = []
    comma_literal_count = 0
    for event in rejections:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), Mapping) else {}
        raw = str(event.get("symbol") or payload.get("symbol") or payload.get("canonical_symbol") or "")
        canonical = str(payload.get("canonical_symbol") or normalize_symbol(raw))
        broker = str(payload.get("broker_symbol") or raw)
        if "," in raw or "," in canonical or "," in broker:
            comma_literal_count += 1
        raw_counter[raw or "UNKNOWN"] += 1
        canonical_counter[normalize_symbol(canonical) or "UNKNOWN"] += 1
        broker_counter[broker or "UNKNOWN"] += 1
        if broker and normalize_symbol(broker) == normalize_symbol(canonical) and broker.upper() != canonical.upper():
            suffix_mismatches.append({"raw_symbol": raw, "canonical_symbol": canonical, "broker_symbol": broker, "normalized": normalize_symbol(broker)})
    status = "OK"
    if comma_literal_count:
        status = "CLI_SYMBOL_PARSE_SUSPECT"
    elif suffix_mismatches:
        status = "BROKER_SUFFIX_SUSPECT"
    return {
        "normalization_status": status,
        "raw_symbol_counts": _rows(raw_counter, "symbol"),
        "canonical_symbol_counts": _rows(canonical_counter, "canonical_symbol"),
        "broker_symbol_counts": _rows(broker_counter, "broker_symbol"),
        "broker_suffix_mismatch_count": len(suffix_mismatches),
        "broker_suffix_examples": suffix_mismatches[:10],
        "cli_comma_literal_symbol_count": comma_literal_count,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _rows(counter: Counter[str], key: str) -> list[dict[str, Any]]:
    return [{key: symbol, "count": count, "execution_attempted": False, "order_send_called": False, "order_check_called": False} for symbol, count in counter.most_common()]
