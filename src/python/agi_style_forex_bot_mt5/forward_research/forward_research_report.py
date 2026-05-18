"""Forward candidate research report orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .candidate_event_loader import load_forward_candidates
from .candidate_replay import replay_candidates, replay_summary
from .ensemble_score_analyzer import analyze_ensemble_scores
from .regime_mismatch_analyzer import analyze_regime_mismatches
from .research_variant_runner import run_research_variants


def run_forward_candidate_replay(
    *,
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    diagnostics_dir: str | Path = "data/reports/forward_diagnostics",
    sqlite_path: str | Path | None = None,
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/forward_research",
) -> dict[str, Any]:
    """Replay forward candidates in research-only mode."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    loaded = load_forward_candidates(log_dir=log_dir, diagnostics_dir=diagnostics_dir, sqlite_path=sqlite_path)
    replay_rows = replay_candidates(loaded.candidates)
    replay = replay_summary(replay_rows)
    regime = analyze_regime_mismatches(loaded.candidates)
    ensemble = analyze_ensemble_scores(loaded.candidates)
    sensitivity, variant_rows = run_research_variants(loaded.candidates)
    paths = _write_reports(output, replay, replay_rows, regime, ensemble, sensitivity, variant_rows)
    return {
        **replay,
        "sources": loaded.sources,
        "profile_config": str(profile_config or ""),
        "regime_mismatch_status": "OK" if regime.get("blocked_by_regime") else "NO_REGIME_BLOCKS",
        "ensemble_score_status": "OK" if ensemble.get("candidate_count") else "NO_SCORE_CANDIDATES",
        "reports_created": paths,
        "research_only": True,
        "not_for_demo_live": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def run_forward_blocker_sensitivity(
    *,
    diagnostics_dir: str | Path = "data/reports/forward_diagnostics",
    log_dir: str | Path = "data/logs/forward-shadow-stable",
    profile_config: str | Path | None = None,
    output_dir: str | Path = "data/reports/forward_research",
) -> dict[str, Any]:
    """Run research-only sensitivity variants from diagnostics artifacts."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    loaded = load_forward_candidates(log_dir=log_dir, diagnostics_dir=diagnostics_dir, sqlite_path=None)
    sensitivity, variant_rows = run_research_variants(loaded.candidates)
    regime = analyze_regime_mismatches(loaded.candidates)
    ensemble = analyze_ensemble_scores(loaded.candidates)
    paths = _write_reports(output, {}, [], regime, ensemble, sensitivity, variant_rows)
    return {
        **sensitivity,
        "profile_config": str(profile_config or ""),
        "top_research_blockers": _top_blockers(loaded.candidates),
        "reports_created": paths,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }


def _write_reports(
    output: Path,
    replay: Mapping[str, Any],
    replay_rows: list[dict[str, Any]],
    regime: Mapping[str, Any],
    ensemble: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    variant_rows: list[dict[str, Any]],
) -> list[str]:
    paths = {
        "candidate_replay_summary": output / "candidate_replay_summary.json",
        "candidate_replay": output / "candidate_replay.csv",
        "regime": output / "regime_mismatch_analysis.json",
        "ensemble": output / "ensemble_score_analysis.json",
        "sensitivity": output / "blocker_sensitivity.json",
        "sensitivity_csv": output / "blocker_sensitivity.csv",
        "variants": output / "research_variants.csv",
        "html": output / "report.html",
    }
    _write_json(paths["candidate_replay_summary"], replay or {"mode": "forward-candidate-replay", "status": "NOT_RUN", "execution_attempted": False})
    _frame(replay_rows).to_csv(paths["candidate_replay"], index=False)
    _write_json(paths["regime"], regime)
    _write_json(paths["ensemble"], ensemble)
    _write_json(paths["sensitivity"], sensitivity)
    _frame(variant_rows).to_csv(paths["sensitivity_csv"], index=False)
    _frame(variant_rows).to_csv(paths["variants"], index=False)
    html_payload = {"replay": replay, "regime": regime, "ensemble": ensemble, "sensitivity": sensitivity}
    paths["html"].write_text(f"<html><body><h1>Forward Research</h1><pre>{json.dumps(_jsonable(html_payload), indent=2, sort_keys=True)}</pre></body></html>", encoding="utf-8")
    return [str(path) for path in paths.values()]


def _top_blockers(candidates: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        for blocker in candidate.get("blocking_reasons") or ():
            counts[str(blocker)] = counts.get(str(blocker), 0) + 1
    return [{"blocking_reason": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10]]


def _frame(rows: list[Mapping[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([_flatten(row) for row in rows]) if rows else pd.DataFrame()


def _flatten(row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Mapping):
            result[str(key)] = json.dumps(_jsonable(value), sort_keys=True)
        elif isinstance(value, (tuple, list)):
            result[str(key)] = "|".join(str(item) for item in value)
        else:
            result[str(key)] = value
    return result


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
