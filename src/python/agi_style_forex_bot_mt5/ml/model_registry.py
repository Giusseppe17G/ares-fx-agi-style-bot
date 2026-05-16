"""Model registry for ML meta-filter artifacts."""

from __future__ import annotations

import json
import pickle
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


def save_model_bundle(*, model_dir: Path, model: Any, calibrator: Any, metadata: Mapping[str, Any], metrics: Mapping[str, Any], training_manifest: Mapping[str, Any]) -> str:
    model_dir.mkdir(parents=True, exist_ok=True)
    model_id = f"mlf_{uuid4().hex}"
    (model_dir / "model.pkl").write_bytes(pickle.dumps(model))
    (model_dir / "calibrator.pkl").write_bytes(pickle.dumps(calibrator))
    full_metadata = {
        "model_id": model_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "train_range": "",
        "validation_range": "",
        "test_range": "",
        "dataset_fingerprint": "",
        **dict(metadata),
    }
    (model_dir / "metadata.json").write_text(json.dumps(full_metadata, indent=2, sort_keys=True), encoding="utf-8")
    (model_dir / "feature_schema.json").write_text(json.dumps({"features": metadata.get("features", [])}, indent=2, sort_keys=True), encoding="utf-8")
    (model_dir / "metrics.json").write_text(json.dumps(dict(metrics), indent=2, sort_keys=True), encoding="utf-8")
    (model_dir / "training_manifest.json").write_text(json.dumps(dict(training_manifest), indent=2, sort_keys=True), encoding="utf-8")
    return model_id


def load_model_bundle(model_dir: str | Path) -> dict[str, Any] | None:
    directory = Path(model_dir)
    required = ["model.pkl", "calibrator.pkl", "metadata.json", "feature_schema.json", "metrics.json"]
    if not all((directory / name).exists() for name in required):
        return None
    try:
        return {
            "model": pickle.loads((directory / "model.pkl").read_bytes()),
            "calibrator": pickle.loads((directory / "calibrator.pkl").read_bytes()),
            "metadata": json.loads((directory / "metadata.json").read_text(encoding="utf-8")),
            "feature_schema": json.loads((directory / "feature_schema.json").read_text(encoding="utf-8")),
            "metrics": json.loads((directory / "metrics.json").read_text(encoding="utf-8")),
        }
    except Exception:
        return None


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""

