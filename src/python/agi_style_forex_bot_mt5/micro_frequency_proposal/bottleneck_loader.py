"""Load micro frequency bottleneck context without mutating runtime state."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def load_bottleneck_context(
    *,
    frequency_dir: str | Path = "data/reports/micro_frequency_calibration",
    v2_review_dir: str | Path = "data/reports/micro_v2_review",
) -> dict[str, Any]:
    frequency = Path(frequency_dir)
    review = Path(v2_review_dir)
    return {
        "frequency_dir": str(frequency),
        "v2_review_dir": str(review),
        "micro_frequency_summary": _load_json(frequency / "micro_frequency_summary.json"),
        "frequency_bottlenecks": _load_csv(frequency / "frequency_bottlenecks.csv"),
        "threshold_sensitivity": _load_csv(frequency / "threshold_sensitivity.csv"),
        "symbol_frequency": _load_csv(frequency / "symbol_frequency.csv"),
        "session_opportunity": _load_csv(frequency / "session_opportunity.csv"),
        "micro_v2_review_summary": _load_json(review / "micro_v2_review_summary.json"),
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _load_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []
