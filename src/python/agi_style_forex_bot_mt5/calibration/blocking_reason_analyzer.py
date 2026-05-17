"""Blocking reason aggregation for signal calibration."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


def analyze_blocking_reasons(records: Iterable[Mapping[str, Any]], *, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Aggregate blocking reasons and context dimensions."""

    rows = [_flatten_record(record) for record in records]
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=["symbol", "strategy", "regime", "session", "blocking_reason", "component", "component_score"])
    reason_counts = frame["blocking_reason"].value_counts().reset_index() if "blocking_reason" in frame else pd.DataFrame(columns=["blocking_reason", "count"])
    if not reason_counts.empty:
        reason_counts.columns = ["blocking_reason", "count"]
    outputs: list[str] = []
    if output_dir is not None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        paths = {
            "blocking": output / "blocking_reasons.csv",
            "symbol": output / "by_symbol.csv",
            "strategy": output / "by_strategy.csv",
            "regime": output / "by_regime.csv",
            "session": output / "by_session.csv",
        }
        reason_counts.to_csv(paths["blocking"], index=False)
        _count_by(frame, "symbol").to_csv(paths["symbol"], index=False)
        _count_by(frame, "strategy").to_csv(paths["strategy"], index=False)
        _count_by(frame, "regime").to_csv(paths["regime"], index=False)
        _count_by(frame, "session").to_csv(paths["session"], index=False)
        outputs = [str(path) for path in paths.values()]
    return {
        "top_blocking_reasons": reason_counts.head(10).to_dict("records"),
        "records_analyzed": len(rows),
        "reports_created": outputs,
        "execution_attempted": False,
    }


def load_strategy_diagnostics(reports_root: str | Path) -> list[dict[str, Any]]:
    """Load strategy diagnostics from report files."""

    root = Path(reports_root)
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/strategy_diagnose.json")) + sorted(root.glob("**/strategy_diagnostics.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if "diagnostics" in payload and isinstance(payload["diagnostics"], list):
            records.extend(dict(item) for item in payload["diagnostics"])
        else:
            records.append(payload)
    return records


def _flatten_record(record: Mapping[str, Any]) -> dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    component_scores = dict(metadata.get("component_scores") or record.get("component_scores") or {})
    blocking = record.get("blocking_reasons") or metadata.get("blocking_reasons") or record.get("reasons") or ("unknown",)
    if isinstance(blocking, str):
        blocking = (blocking,)
    reason = str(next(iter(blocking), "unknown"))
    weakest_component = _weakest_component(component_scores)
    return {
        "symbol": str(record.get("symbol", "")),
        "strategy": str(record.get("strategy_name") or metadata.get("suggested_strategy_name") or ""),
        "regime": str(record.get("regime") or metadata.get("regime") or ""),
        "session": str(record.get("session") or metadata.get("session") or ""),
        "blocking_reason": reason,
        "component": weakest_component[0],
        "component_score": weakest_component[1],
    }


def _weakest_component(component_scores: Mapping[str, Any]) -> tuple[str, float]:
    if not component_scores:
        return "", 0.0
    parsed = {str(key): float(value) for key, value in component_scores.items()}
    key = min(parsed, key=parsed.get)
    return key, parsed[key]


def _count_by(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=[column, "count"])
    return frame[column].fillna("").astype(str).value_counts().reset_index(name="count").rename(columns={"index": column})
