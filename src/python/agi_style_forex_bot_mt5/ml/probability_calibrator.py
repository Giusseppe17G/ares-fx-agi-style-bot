"""Probability calibration helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SigmoidCalibrator:
    a: float
    b: float

    @staticmethod
    def fit(probabilities: np.ndarray, labels: np.ndarray) -> "SigmoidCalibrator":
        logits = np.log(np.clip(probabilities, 1e-6, 1 - 1e-6) / np.clip(1 - probabilities, 1e-6, 1))
        a = 1.0
        b = 0.0
        for _ in range(200):
            pred = 1.0 / (1.0 + np.exp(-np.clip(a * logits + b, -30, 30)))
            error = pred - labels
            a -= 0.05 * float((error * logits).mean())
            b -= 0.05 * float(error.mean())
        return SigmoidCalibrator(a=a, b=b)

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        logits = np.log(np.clip(probabilities, 1e-6, 1 - 1e-6) / np.clip(1 - probabilities, 1e-6, 1))
        return 1.0 / (1.0 + np.exp(-np.clip(self.a * logits + self.b, -30, 30)))


def brier_score(labels: np.ndarray, probabilities: np.ndarray) -> float:
    if len(labels) == 0:
        return 0.0
    return float(np.mean((probabilities - labels) ** 2))


def calibration_error(labels: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    if len(labels) == 0:
        return 0.0
    total = 0.0
    for lower in np.linspace(0, 1, bins, endpoint=False):
        upper = lower + 1 / bins
        mask = (probabilities >= lower) & (probabilities < upper)
        if mask.any():
            total += float(abs(probabilities[mask].mean() - labels[mask].mean()) * mask.mean())
    return total


def write_calibration_curve(path: str | Path, labels: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> None:
    rows = []
    for lower in np.linspace(0, 1, bins, endpoint=False):
        upper = lower + 1 / bins
        mask = (probabilities >= lower) & (probabilities < upper)
        rows.append(
            {
                "bin_lower": lower,
                "bin_upper": upper,
                "mean_probability": float(probabilities[mask].mean()) if mask.any() else 0.0,
                "winrate": float(labels[mask].mean()) if mask.any() else 0.0,
                "count": int(mask.sum()),
            }
        )
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["bin_lower", "bin_upper", "mean_probability", "winrate", "count"])
        writer.writeheader()
        writer.writerows(rows)

