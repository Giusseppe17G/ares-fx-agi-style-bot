"""Durable, offline execution of the fixed predeclared research matrix.

This runner records every comparison cell. It never selects a winner, copies
training metrics to another split, loads a model or accesses a terminal.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ..backtesting.backtester import CostModel
from ..core.clock import FrozenClock
from ..core.instruments import InstrumentSpec
from ..core.run_manifest import RunManifest
from ..core.safety import SafetyEnvelope
from ..core.workspace import WorkspacePaths, workspace_paths
from .experiment_plan import (ExperimentPlan, ResearchManagement, build_experiment_plan,
    dataframe_sha256, normalize_research_bars, validate_plan_datasets)
from .trend_pullback_evaluator import evaluate_trend_pullback


SCOPE = "PREDECLARED_INDEPENDENT_CANDIDATE_RESEARCH"
CSV_FIELDS = ("timestamp_utc", "open", "high", "low", "close", "volume", "spread_points")


@dataclass(frozen=True)
class PredeclaredResearchResult:
    payload: Mapping[str, Any]

    def to_dict(self):
        return strict_json_loads(canonical_json(self.payload))


class ResearchBindingError(ValueError):
    """An input no longer matches the persisted predeclared experiment."""


def canonical_json(value):
    return json.dumps(value, default=_json_default, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False)


def strict_json_loads(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def invalid(_value):
        raise ValueError("nonfinite JSON constant")
    value = json.loads(text, object_pairs_hook=unique, parse_constant=invalid)
    # json.loads can parse 1e999 as infinity without invoking parse_constant.
    canonical_json(value)
    return value


def current_source_manifest(*, config=None, dataset_hash="", symbols=(), reference_time=None):
    source_root = Path(__file__).resolve().parents[4]
    workspace = WorkspacePaths.resolve(project_root=source_root, data_root=workspace_paths().data_root)
    clock = FrozenClock(pd.Timestamp(reference_time)) if reference_time is not None else None
    return RunManifest.build(mode="predeclared_trend_pullback", workspace=workspace, clock=clock,
        config=config, dataset_hash=dataset_hash, symbols=symbols, timeframe="M5")


def run_predeclared_research(plan: ExperimentPlan, datasets: Mapping[str, pd.DataFrame], *,
        output_dir: str | Path, dataset_paths: Mapping[str, str | Path] | None = None) -> PredeclaredResearchResult:
    """Run every hypothesis/symbol/split after persisting its frozen inputs.

    The output directory must not exist. Invalid initial bindings leave no run.
    Evaluator failures are recorded per cell; a changed input/code binding stops
    further evaluation and records all remaining cells as NOT_EVALUATED.
    """
    if not isinstance(plan, ExperimentPlan):
        raise TypeError("an ExperimentPlan is required")
    frozen_text = plan.canonical_json
    plan = ExperimentPlan.from_json(frozen_text)
    payload = plan.to_dict()
    paths = None if dataset_paths is None else {symbol: Path(path).resolve() for symbol, path in dataset_paths.items()}
    manifest = _verify_bindings(plan, datasets, paths, verify_raw_contents=True)
    frames = {symbol: frame.copy(deep=True) for symbol, frame in datasets.items()}
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    # Exclusive, durable and reread before any evaluator is called.
    _write_text_new(output / "plan.json", frozen_text)
    input_description = {"plan_id": plan.plan_id, "data_role": payload["data_role"],
        "raw_source_hash_verified": paths is not None,
        "raw_source_verification": "VERIFIED_CONTENT_ONLY" if paths is not None else "NOT_AVAILABLE",
        "source_authenticity_verified": False, "datasets": payload["datasets"],
        "dataset_paths": {} if paths is None else {key: str(value) for key, value in paths.items()}}
    _write_json_new(output / "inputs.json", input_description)
    _write_json_new(output / "manifest.json", {"status": "PREDECLARED", "plan_id": plan.plan_id,
        "plan_document_sha256": _file_sha256(output / "plan.json"), "run_manifest": manifest.as_dict(),
        **_limitations(payload["data_role"])})
    if ExperimentPlan.from_json((output / "plan.json").read_text(encoding="utf-8")).plan_id != plan.plan_id:
        raise OSError("persisted experiment plan verification failed")
    for folder in ("cells", "decisions", "trades"):
        (output / folder).mkdir()
    cells = []
    journal_sequence = 0
    binding_failure = None
    with (output / "journal.jsonl").open("x", encoding="utf-8", newline="\n") as journal:
        def record(event_type, item):
            nonlocal journal_sequence
            journal_sequence += 1
            journal.write(canonical_json({"sequence": journal_sequence, "event_type": event_type,
                "plan_id": plan.plan_id, **item, "execution_authorized": False}) + "\n")
            journal.flush()
            os.fsync(journal.fileno())

        record("PLAN_PERSISTED", {"plan_document_sha256": _file_sha256(output / "plan.json")})
        for hypothesis in plan.hypotheses:
            for symbol in plan.symbols:
                for split in plan.splits:
                    identity = {"plan_id": plan.plan_id, "hypothesis_id": hypothesis.hypothesis_id,
                        "symbol": symbol, "split": split.name}
                    cell_id = _digest(identity)
                    identity["cell_id"] = cell_id
                    cell = {**identity, "status": "NOT_EVALUATED", "metrics": None,
                        "evaluation_id": None, "error_type": None, "reject_code": None}
                    attempted = False
                    try:
                        if binding_failure is not None:
                            raise ResearchBindingError(binding_failure)
                        _verify_bindings(plan, datasets, paths)
                        if (output / "plan.json").read_text(encoding="utf-8") != frozen_text:
                            raise ResearchBindingError("PERSISTED_PLAN_CHANGED")
                        record("EVALUATION_STARTED", identity)
                        attempted = True
                        evaluation = evaluate_trend_pullback(plan, frames[symbol].copy(deep=True),
                            symbol=symbol, hypothesis_id=hypothesis.hypothesis_id, split=split.name)
                        _verify_bindings(plan, datasets, paths)
                        if (output / "plan.json").read_text(encoding="utf-8") != frozen_text:
                            raise ResearchBindingError("PERSISTED_PLAN_CHANGED")
                        evaluation_payload = evaluation.to_dict()
                        expected = {"plan_id": plan.plan_id, "hypothesis_id": hypothesis.hypothesis_id,
                            "symbol": symbol, "split": split.name}
                        if (any(evaluation_payload.get(key) != value for key, value in expected.items())
                                or evaluation.status not in {"COMPLETED", "NO_TRADES", "NO_CANDIDATES", "INSUFFICIENT_DATA"}
                                or evaluation_payload.get("status") != evaluation.status
                                or any(evaluation_payload.get(key) is not False for key in
                                       ("full_risk_pipeline_applied", "full_pipeline_verified", "promotion_eligible"))):
                            raise ValueError("evaluator output does not match this research cell")
                        # Validate before creating any cell result. A custom
                        # evaluator cannot smuggle NaN/Infinity into evidence.
                        canonical_json(evaluation_payload)
                        decision_path = Path("decisions") / f"{cell_id}.jsonl"
                        trade_path = Path("trades") / f"{cell_id}.jsonl"
                        _write_jsonl_new(output / decision_path, evaluation.decisions)
                        trades = () if evaluation.outcome is None else evaluation.outcome.trades
                        _write_jsonl_new(output / trade_path, (asdict(trade) for trade in trades))
                        # Complete per-cell output retains evaluator rejection
                        # evidence; the summary never aggregates unrelated splits.
                        cell.update(status=evaluation.status, evaluation_id=evaluation.evaluation_id,
                            metrics=evaluation_payload.get("metrics"), evaluation=evaluation_payload,
                            profit_factor_status=evaluation_payload["profit_factor_status"],
                            denomination_currency=payload["denomination_currency"],
                            decision_count=len(evaluation.decisions), trade_count=len(trades),
                            decisions_path=decision_path.as_posix(), decisions_sha256=_file_sha256(output / decision_path),
                            trades_path=trade_path.as_posix(), trades_sha256=_file_sha256(output / trade_path))
                    except ResearchBindingError as exc:
                        binding_failure = str(exc)
                        cell.update(status="FAILED" if attempted else "NOT_EVALUATED",
                            reject_code=binding_failure, error_type=type(exc).__name__)
                        record("EVALUATION_BLOCKED", {**identity, "reject_code": binding_failure})
                    except (OSError, KeyboardInterrupt):
                        # Losing the required persistence journal aborts the
                        # process. Already-written artifacts remain reviewable;
                        # there is no success summary or automatic retry.
                        raise
                    except Exception as exc:
                        cell.update(status="FAILED", reject_code="EVALUATION_FAILED", error_type=type(exc).__name__)
                        record("EVALUATION_FAILED", {**identity, "error_type": type(exc).__name__})
                    _write_json_new(output / "cells" / f"{cell_id}.json", {**cell, **_limitations(payload["data_role"])})
                    if cell["evaluation_id"] is not None:
                        record("EVALUATION_COMPLETED", {**identity, "evaluation_id": cell["evaluation_id"], "status": cell["status"]})
                    cells.append({key: value for key, value in cell.items() if key != "evaluation"})
        record("COMPARISON_COMPLETED", {"cell_count": len(cells), "selection_policy": "NONE_COMPARE_ALL"})
    incomplete = any(cell["status"] in {"FAILED", "NOT_EVALUATED"} for cell in cells)
    summary = {"schema_version": "1.0", "plan_id": plan.plan_id, "run_id": manifest.run_id,
        "denomination_currency": payload["denomination_currency"],
        "status": "INCOMPLETE" if incomplete else "COMPLETED", "cells": cells,
        "cell_count": len(cells), "raw_source_hash_verified": paths is not None,
        "source_authenticity_verified": False, **_limitations(payload["data_role"])}
    summary["result_id"] = _digest(summary)
    _write_json_new(output / "summary.json", summary)
    return PredeclaredResearchResult(summary)


def _verify_bindings(plan, datasets, paths, *, verify_raw_contents=False):
    payload = plan.to_dict()
    try:
        validate_plan_datasets(plan, datasets)
    except ValueError as exc:
        raise ResearchBindingError("DATASET_BINDING_MISMATCH") from exc
    manifest = current_source_manifest(config={"plan_id": plan.plan_id},
        dataset_hash=_digest({key: item["data_sha256"] for key, item in payload["datasets"].items()}),
        symbols=plan.symbols, reference_time=plan.splits[0].start_utc)
    if manifest.git_commit_sha != payload["code_commit"] or manifest.source_tree_hash != payload["source_sha256"]:
        raise ResearchBindingError("SOURCE_BINDING_MISMATCH")
    if paths is not None:
        if set(paths) != set(plan.symbols):
            raise ResearchBindingError("DATASET_PATH_SYMBOLS_MISMATCH")
        for symbol, path in paths.items():
            try:
                raw_hash = _file_sha256(path)
            except OSError as exc:
                raise ResearchBindingError("RAW_DATA_SOURCE_UNAVAILABLE") from exc
            if raw_hash != payload["datasets"][symbol]["data_provenance"]["source_sha256"]:
                raise ResearchBindingError("RAW_DATA_SOURCE_BINDING_MISMATCH")
            if verify_raw_contents and dataframe_sha256(_read_research_csv(path, symbol=symbol), symbol=symbol) != payload["datasets"][symbol]["data_sha256"]:
                raise ResearchBindingError("RAW_DATA_FRAME_BINDING_MISMATCH")
    return manifest


def load_study_inputs(path: str | Path):
    """Read an explicit canonical CSV study description; never discover files."""
    path = Path(path).resolve()
    inputs = strict_json_loads(path.read_text(encoding="utf-8"))
    _keys(inputs, {"data_role", "denomination_currency", "initial_balance", "lot", "random_seed", "management", "datasets"}, "study")
    _keys(inputs["management"], {field.name for field in fields(ResearchManagement)}, "management")
    management = ResearchManagement(**inputs["management"])
    frames, paths, instruments, costs, data_provenance, cost_provenance = {}, {}, {}, {}, {}, {}
    if not isinstance(inputs["datasets"], dict) or not inputs["datasets"]:
        raise ValueError("explicit datasets are required")
    for symbol, item in inputs["datasets"].items():
        _keys(item, {"path", "provider", "quality_report", "tick_value_currency", "tick_value_status",
            "instrument", "cost_model", "cost_provenance"}, "dataset")
        candidate_path = Path(item["path"])
        dataset_path = candidate_path if candidate_path.is_absolute() else path.parent / candidate_path
        paths[symbol] = dataset_path.resolve()
        frames[symbol] = _read_research_csv(dataset_path, symbol=symbol)
        spec_fields = {field.name for field in fields(InstrumentSpec)}
        actual = set(item["instrument"])
        if actual not in (spec_fields, spec_fields - {"currency_margin"}):
            raise ValueError("all explicit InstrumentSpec fields are required")
        instruments[symbol] = InstrumentSpec(**item["instrument"]).validate()
        _keys(item["cost_model"], {field.name for field in fields(CostModel)}, "cost_model")
        costs[symbol] = CostModel(**item["cost_model"])
        data_provenance[symbol] = {"source_sha256": _file_sha256(dataset_path),
            "provider": item["provider"], "quality_report": item["quality_report"],
            "tick_value_currency": item["tick_value_currency"], "tick_value_status": item["tick_value_status"]}
        cost_provenance[symbol] = item["cost_provenance"]
    return {"datasets": frames, "dataset_paths": paths, "instruments": instruments, "cost_models": costs,
        "data_provenance": data_provenance, "cost_provenance": cost_provenance,
        "data_role": inputs["data_role"], "denomination_currency": inputs["denomination_currency"],
        "lot": inputs["lot"], "initial_balance": inputs["initial_balance"],
        "management": management, "random_seed": inputs["random_seed"]}


def prepare_study_plan(inputs_path: str | Path) -> tuple[ExperimentPlan, Mapping[str, Any]]:
    loaded = load_study_inputs(inputs_path)
    source = current_source_manifest()
    plan = build_experiment_plan(**{key: value for key, value in loaded.items() if key != "dataset_paths"},
        code_commit=source.git_commit_sha, source_sha256=source.source_tree_hash)
    return plan, loaded


def _read_research_csv(path, *, symbol):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), ())
    if len(header) != len(set(header)) or set(header) != set(CSV_FIELDS):
        raise ValueError("canonical CSV requires the seven unique documented fields")
    frame = pd.read_csv(path, float_precision="round_trip")
    return normalize_research_bars(frame, symbol=symbol)


def write_plan_new(plan, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_new(path, plan.canonical_json)


def _limitations(role):
    return SafetyEnvelope().seal({"scope": SCOPE, "data_role": role,
        "selection_policy": "NONE_COMPARE_ALL", "selected_hypothesis_id": None,
        "final_holdout": "NOT_AVAILABLE", "walk_forward": "NOT_EVALUATED", "baselines": "NOT_EVALUATED",
        "full_risk_pipeline_applied": False, "full_pipeline_verified": False,
        "runtime_code_binding": "DISK_SOURCE_HASH_NOT_LOADED_MODULE_ATTESTATION",
        "promotion_eligible": False, "operationally_eligible": False, "execution_authorized": False}, full=True)


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} requires exactly its documented fields")


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _json_default(value):
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("research timestamps must be timezone-aware")
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported research JSON value: {type(value).__name__}")


def _write_text_new(path, text):
    encoded = text.encode("utf-8")
    with Path(path).open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    if Path(path).read_bytes() != encoded:
        raise OSError("research artifact verification failed")


def _write_json_new(path, payload):
    _write_text_new(path, canonical_json(payload) + "\n")


def _write_jsonl_new(path, rows):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
