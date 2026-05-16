"""Runtime ML meta-filter for shadow-only signal quality."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .feature_store import _feature_row
from .model_registry import load_model_bundle
from .model_trainer import NUMERIC_FEATURES


@dataclass(frozen=True)
class MLFilterDecision:
    ml_status: str
    probability_of_success: float | None
    expected_r: float | None
    mae_risk: float | None
    mfe_potential: float | None
    setup_quality: str | None
    threshold_used: float
    reasons: tuple[str, ...]
    execution_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MLFilter:
    """Load and apply an approved ML meta-filter, fail-safe by default."""

    def __init__(self, model_dir: str | Path = "data/models/ml_filter", *, minimum_probability_for_shadow_trade: float = 0.58, high_quality_threshold: float = 0.68, reject_below: float = 0.55) -> None:
        self.model_dir = Path(model_dir)
        self.minimum_probability_for_shadow_trade = minimum_probability_for_shadow_trade
        self.high_quality_threshold = high_quality_threshold
        self.reject_below = reject_below
        self.bundle = load_model_bundle(self.model_dir)

    @staticmethod
    def load_latest_model(model_dir: str | Path = "data/models/ml_filter") -> "MLFilter":
        return MLFilter(model_dir)

    def predict_signal_quality(self, signal: Any, features: Mapping[str, Any]) -> MLFilterDecision:
        if self.bundle is None:
            return self._disabled("no approved model bundle found")
        metadata = self.bundle["metadata"]
        if not metadata.get("approved_for_shadow_filtering", False):
            return self._disabled(metadata.get("rejection_reason") or "model is not approved")
        try:
            row = _feature_row(
                getattr(signal, "signal_id", ""),
                getattr(signal, "created_at_utc").isoformat() if getattr(signal, "created_at_utc", None) else "",
                getattr(signal, "symbol", ""),
                {"score": features.get("score", 0.0), "features": features, "strategy_name": getattr(signal, "strategy_name", "")},
            )
            x = np.array([[float(row.get(column) or 0.0) for column in NUMERIC_FEATURES]], dtype=float)
            raw = self.bundle["model"].predict_proba(x)
            probability = float(self.bundle["calibrator"].predict(raw)[0])
            status = "ML_APPROVED" if probability >= self.minimum_probability_for_shadow_trade else "ML_REJECTED"
            quality = "A" if probability >= self.high_quality_threshold else "B" if probability >= self.minimum_probability_for_shadow_trade else "C" if probability >= self.reject_below else "D"
            return MLFilterDecision(
                ml_status=status,
                probability_of_success=probability,
                expected_r=(probability - 0.5) * 2.0,
                mae_risk=max(0.0, 1.0 - probability),
                mfe_potential=probability,
                setup_quality=quality,
                threshold_used=self.minimum_probability_for_shadow_trade,
                reasons=("probability below threshold",) if status == "ML_REJECTED" else ("model approved signal for shadow filtering",),
                execution_attempted=False,
            )
        except Exception as exc:
            return MLFilterDecision("ML_ERROR", None, None, None, None, None, self.minimum_probability_for_shadow_trade, (str(exc),), False)

    def approve_or_reject(self, signal: Any, features: Mapping[str, Any]) -> MLFilterDecision:
        return self.predict_signal_quality(signal, features)

    def _disabled(self, reason: str) -> MLFilterDecision:
        return MLFilterDecision("ML_DISABLED", None, None, None, None, None, self.minimum_probability_for_shadow_trade, (reason,), False)

