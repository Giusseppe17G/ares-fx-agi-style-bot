"""Train a lightweight ML meta-filter baseline."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from .feature_store import FEATURE_COLUMNS
from .model_registry import save_model_bundle
from .probability_calibrator import SigmoidCalibrator, brier_score, calibration_error


NUMERIC_FEATURES = tuple(column for column in FEATURE_COLUMNS if column not in {"signal_id", "timestamp_utc", "symbol"})


class LogisticBaseline:
    """Small deterministic logistic regression baseline using numpy."""

    def __init__(self, weights: np.ndarray, bias: float, feature_names: tuple[str, ...]) -> None:
        self.weights = weights
        self.bias = bias
        self.feature_names = feature_names

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        logits = x @ self.weights + self.bias
        return 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))


def train_ml_filter(*, dataset_path: str | Path, model_dir: str | Path, report_dir: str | Path, min_samples: int = 10) -> dict[str, Any]:
    rows = _read_csv(Path(dataset_path))
    report = Path(report_dir)
    report.mkdir(parents=True, exist_ok=True)
    if len(rows) < min_samples:
        summary = _disabled_summary("insufficient samples", len(rows), report)
        return summary
    x, y, splits, r_values = _matrix(rows)
    train_mask = splits == "train"
    val_mask = splits == "validation"
    test_mask = splits == "test"
    if train_mask.sum() == 0 or len(set(y[train_mask].tolist())) < 2:
        return _disabled_summary("train split needs both classes", len(rows), report)
    model = _fit_logistic(x[train_mask], y[train_mask])
    raw_val = model.predict_proba(x[val_mask]) if val_mask.any() else model.predict_proba(x[train_mask])
    val_y = y[val_mask] if val_mask.any() else y[train_mask]
    calibrator = SigmoidCalibrator.fit(raw_val, val_y)
    pred_test_raw = model.predict_proba(x[test_mask]) if test_mask.any() else raw_val
    test_y = y[test_mask] if test_mask.any() else val_y
    pred_test = calibrator.predict(pred_test_raw)
    metrics = _metrics(test_y, pred_test, r_values[test_mask] if test_mask.any() else r_values[val_mask] if val_mask.any() else r_values[train_mask])
    metrics["brier_before_calibration"] = brier_score(test_y, pred_test_raw)
    metrics["brier_after_calibration"] = brier_score(test_y, pred_test)
    metrics["calibration_error"] = calibration_error(test_y, pred_test)
    approved = len(rows) >= min_samples and metrics["brier_after_calibration"] <= max(0.35, metrics["brier_before_calibration"] + 0.1)
    model_id = save_model_bundle(
        model_dir=Path(model_dir),
        model=model,
        calibrator=calibrator,
        metadata={
            "model_type": "LogisticRegressionBaseline",
            "features": list(NUMERIC_FEATURES),
            "labels": ["label_win"],
            "approved_for_shadow_filtering": approved,
            "rejection_reason": "" if approved else "calibration or sample requirements not met",
        },
        metrics=metrics,
        training_manifest={
            "samples": len(rows),
            "train_samples": int(train_mask.sum()),
            "validation_samples": int(val_mask.sum()),
            "test_samples": int(test_mask.sum()),
        },
    )
    summary = {
        "mode": "train-ml-filter",
        "samples": len(rows),
        "model_status": "ML_APPROVED" if approved else "WATCHLIST",
        "approved_for_shadow_filtering": approved,
        "model_id": model_id,
        "metrics": metrics,
        "reports_created": [str(Path(model_dir) / "metadata.json"), str(Path(model_dir) / "metrics.json")],
        "execution_attempted": False,
    }
    (report / "training_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["reports_created"].append(str(report / "training_summary.json"))
    return summary


def _fit_logistic(x: np.ndarray, y: np.ndarray) -> LogisticBaseline:
    mean = x.mean(axis=0)
    std = x.std(axis=0) + 1e-9
    x_scaled = (x - mean) / std
    weights = np.zeros(x_scaled.shape[1])
    bias = 0.0
    lr = 0.1
    pos_weight = len(y) / max(1, 2 * y.sum())
    neg_weight = len(y) / max(1, 2 * (len(y) - y.sum()))
    sample_weight = np.where(y == 1, pos_weight, neg_weight)
    for _ in range(250):
        pred = 1.0 / (1.0 + np.exp(-np.clip(x_scaled @ weights + bias, -30, 30)))
        error = (pred - y) * sample_weight
        weights -= lr * (x_scaled.T @ error) / len(y)
        bias -= lr * float(error.mean())
    model = LogisticBaseline(weights / std, float(bias - (mean / std) @ weights), NUMERIC_FEATURES)
    return model


def _metrics(y: np.ndarray, p: np.ndarray, r_values: np.ndarray) -> dict[str, Any]:
    pred = (p >= 0.5).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    return {
        "auc": _auc(y, p),
        "accuracy": float((pred == y).mean()) if len(y) else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": (2 * precision * recall / max(1e-9, precision + recall)),
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "profit_aware_metric": float(r_values[p >= 0.5].sum()) if len(r_values) else 0.0,
    }


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    if len(set(y.tolist())) < 2:
        return 0.5
    order = np.argsort(p)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    pos = y == 1
    n_pos = pos.sum()
    n_neg = len(y) - n_pos
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / max(1, n_pos * n_neg))


def _matrix(rows: list[dict[str, str]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x = np.array([[float(row.get(column) or 0.0) for column in NUMERIC_FEATURES] for row in rows], dtype=float)
    y = np.array([float(row.get("label_win") or 0.0) for row in rows], dtype=float)
    splits = np.array([row.get("split") or "train" for row in rows])
    r_values = np.array([float(row.get("label_expected_r") or 0.0) for row in rows], dtype=float)
    return x, y, splits, r_values


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _disabled_summary(reason: str, samples: int, report: Path) -> dict[str, Any]:
    report.mkdir(parents=True, exist_ok=True)
    summary = {
        "mode": "train-ml-filter",
        "samples": samples,
        "model_status": "WATCHLIST",
        "approved_for_shadow_filtering": False,
        "rejection_reason": reason,
        "reports_created": [str(report / "training_summary.json")],
        "execution_attempted": False,
    }
    (report / "training_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary

