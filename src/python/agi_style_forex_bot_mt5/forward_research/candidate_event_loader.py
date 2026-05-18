"""Load blocked forward candidates from read-only diagnostics artifacts."""

from __future__ import annotations

import json
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


CANDIDATE_EVENTS = {"FORWARD_CANDIDATE_EVALUATED", "FORWARD_CANDIDATE_BLOCKED", "FORWARD_NEAR_MISS"}


@dataclass(frozen=True)
class CandidateLoadResult:
    candidates: list[dict[str, Any]]
    sources: list[str]
    status: str


def load_forward_candidates(
    *,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    diagnostics_dir: str | Path = "data/reports/forward_diagnostics",
    sqlite_path: str | Path | None = None,
) -> CandidateLoadResult:
    """Read candidate rows from JSONL logs, diagnostics CSVs and optional SQLite."""

    rows: list[dict[str, Any]] = []
    sources: list[str] = []
    logs = sorted(Path(log_dir).glob("*.jsonl")) if Path(log_dir).exists() else []
    for path in logs:
        loaded = _load_jsonl_candidates(path)
        if loaded:
            sources.append(str(path))
            rows.extend(loaded)
    diagnostics = Path(diagnostics_dir)
    for name in ("live_strategy_probe.csv", "near_misses.csv"):
        path = diagnostics / name
        loaded = _load_csv_candidates(path)
        if loaded:
            sources.append(str(path))
            rows.extend(loaded)
    scarcity = _load_json(diagnostics / "signal_scarcity_summary.json")
    if scarcity:
        sources.append(str(diagnostics / "signal_scarcity_summary.json"))
    if sqlite_path:
        loaded = _load_sqlite_candidates(Path(sqlite_path))
        if loaded:
            sources.append(str(sqlite_path))
            rows.extend(loaded)
    normalized = _dedupe([_normalize_candidate(row) for row in rows])
    status = "OK" if normalized else "NO_CANDIDATES"
    return CandidateLoadResult(candidates=normalized, sources=sources, status=status)


def _load_jsonl_candidates(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            event_type = str(record.get("event_type", ""))
            if event_type not in CANDIDATE_EVENTS:
                continue
            payload = _payload(record)
            rows.append({**payload, "event_type": event_type, "timestamp_utc": record.get("timestamp_utc", payload.get("timestamp_utc", "")), "source": str(path)})
    except (OSError, json.JSONDecodeError):
        return rows
    return rows


def _load_csv_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        frame = pd.read_csv(path)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for item in frame.to_dict(orient="records"):
        item["source"] = str(path)
        rows.append(item)
    return rows


def _load_sqlite_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        import sqlite3

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            db_rows = conn.execute(
                "SELECT event_type, timestamp_utc, payload_json FROM events WHERE event_type IN ('FORWARD_CANDIDATE_EVALUATED','FORWARD_CANDIDATE_BLOCKED','FORWARD_NEAR_MISS') ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for row in db_rows:
        payload = _loads(row["payload_json"])
        rows.append({**payload, "event_type": row["event_type"], "timestamp_utc": row["timestamp_utc"], "source": str(path)})
    return rows


def _payload(record: Mapping[str, Any]) -> dict[str, Any]:
    payload_json = record.get("payload_json")
    if isinstance(payload_json, str):
        return _loads(payload_json)
    payload = record.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _loads(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _normalize_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    component_scores = _as_mapping(row.get("component_scores"))
    thresholds = _as_mapping(row.get("thresholds_used"))
    blockers = _as_tuple(row.get("blocking_reasons") or row.get("threshold_failures") or row.get("blockers") or row.get("top_blocking_reason"))
    symbol = str(row.get("symbol") or "").upper()
    strategy_name = str(row.get("strategy_name") or row.get("suggested_strategy_name") or "strategy_ensemble")
    ensemble_score = _float(row.get("ensemble_score", row.get("signal_score", row.get("score", 0.0))))
    threshold = _float(thresholds.get("ensemble_min_score", row.get("threshold", 0.0)))
    candidate_id = str(row.get("candidate_id") or f"{symbol}:{strategy_name}:{row.get('timestamp_utc', '')}:{ensemble_score:.4f}")
    return {
        "candidate_id": candidate_id,
        "timestamp_utc": str(row.get("timestamp_utc") or ""),
        "symbol": symbol,
        "strategy_name": strategy_name,
        "session": str(row.get("session") or ""),
        "regime": str(row.get("regime") or ""),
        "setup_score": _float(row.get("setup_score", row.get("setup_quality_score", 0.0))),
        "ensemble_score": ensemble_score,
        "component_scores": component_scores,
        "thresholds_used": thresholds,
        "blocking_reasons": blockers,
        "signal_profile": str(row.get("signal_profile") or row.get("signal_profile_used") or row.get("profile") or "BALANCED_STABLE"),
        "stable_profile_hash": str(row.get("stable_profile_hash") or row.get("profile_hash") or ""),
        "spread_points": _float(row.get("spread_points", 0.0)),
        "cost_fit": _component(row, component_scores, "cost_fit"),
        "liquidity_fit": _component(row, component_scores, "liquidity_fit"),
        "momentum_fit": _component(row, component_scores, "momentum_fit"),
        "structure_fit": _component(row, component_scores, "structure_fit"),
        "volatility_fit": _component(row, component_scores, "volatility_fit"),
        "risk_reward_fit": _component(row, component_scores, "risk_reward_fit"),
        "passed_thresholds": _bool(row.get("passed_thresholds")),
        "action": str(row.get("action") or "NONE"),
        "near_miss": _bool(row.get("near_miss")),
        "near_miss_distance": _float(row.get("near_miss_distance", max(0.0, threshold - ensemble_score))),
        "source": str(row.get("source") or ""),
        "execution_attempted": False,
    }


def _component(row: Mapping[str, Any], component_scores: Mapping[str, Any], key: str) -> float:
    return _float(row.get(key, component_scores.get(key, 0.0)))


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, Mapping):
                return dict(parsed)
        except (SyntaxError, ValueError):
            pass
        return _loads(value.replace("'", '"')) or _loads(value)
    return {}


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, tuple, set)):
                return tuple(str(item) for item in parsed if str(item))
            if isinstance(parsed, str):
                return (parsed,) if parsed else ()
        except (SyntaxError, ValueError):
            pass
        try:
            parsed = json.loads(text.replace("'", '"'))
            if isinstance(parsed, list):
                return tuple(str(item) for item in parsed if str(item))
        except json.JSONDecodeError:
            pass
        return tuple(item.strip() for item in text.replace("|", ",").split(",") if item.strip())
    try:
        return tuple(str(item) for item in value if str(item))
    except TypeError:
        return (str(value),)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _float(value: Any) -> float:
    try:
        if pd.isna(value):
            return 0.0
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("candidate_id") or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}
