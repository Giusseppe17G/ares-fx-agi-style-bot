"""Build ML training dataset with temporal splits."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.ml.feature_store import FEATURE_COLUMNS, build_feature_store
from agi_style_forex_bot_mt5.ml.label_builder import LABEL_COLUMNS, build_labels
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def build_ml_dataset(*, database: TelemetryDatabase, reports_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    feature_summary = build_feature_store(database, output)
    label_summary = build_labels(database, output)
    features = _read_csv(output / "feature_store.csv")
    labels = {row["signal_id"]: row for row in _read_csv(output / "labels.csv")}
    rows: list[dict[str, Any]] = []
    for feature in features:
        label = labels.get(feature["signal_id"])
        if label is None:
            continue
        if label["label_time_utc"] > feature["timestamp_utc"]:
            rows.append({**feature, **label})
    rows.sort(key=lambda row: row["timestamp_utc"])
    rows = _assign_splits(rows)
    dataset_path = output / "ml_dataset.csv"
    columns = list(FEATURE_COLUMNS) + [column for column in LABEL_COLUMNS if column != "signal_id"] + ["split"]
    _write_csv(dataset_path, rows, columns)
    manifest = {
        "mode": "build-ml-dataset",
        "samples": len(rows),
        "train_samples": sum(1 for row in rows if row["split"] == "train"),
        "validation_samples": sum(1 for row in rows if row["split"] == "validation"),
        "test_samples": sum(1 for row in rows if row["split"] == "test"),
        "feature_fingerprint": feature_summary["feature_fingerprint"],
        "label_fingerprint": label_summary["label_fingerprint"],
        "dataset_fingerprint": _fingerprint(rows),
        "symbols": _counts(rows, "symbol"),
        "strategies": _counts(rows, "strategy_encoded"),
        "regimes": _counts(rows, "regime_encoded"),
        "warnings": ["few samples"] if len(rows) < 30 else [],
        "reports_created": [str(dataset_path), str(output / "dataset_manifest.json")],
        "execution_attempted": False,
    }
    (output / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _assign_splits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = len(rows)
    for index, row in enumerate(rows):
        frac = index / max(total, 1)
        row["split"] = "train" if frac < 0.6 else "validation" if frac < 0.8 else "test"
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        out[value] = out.get(value, 0) + 1
    return out


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()
