"""Build ML labels from closed paper/backtest trades."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


LABEL_COLUMNS = (
    "signal_id",
    "label_time_utc",
    "label_win",
    "label_hit_tp",
    "label_expected_r",
    "label_bad_mae",
    "label_good_mfe",
    "label_hold_quality",
)


def build_labels(database: TelemetryDatabase, output_dir: str | Path, *, mae_threshold_r: float = -0.8, mfe_threshold_r: float = 1.0) -> dict[str, Any]:
    rows = []
    for item in database.fetch_paper_trades():
        payload = json.loads(item["payload_json"])
        if payload.get("status") != "CLOSED":
            continue
        signal_id = str(payload.get("signal_id") or "")
        entry_time = str(payload.get("entry_time_utc") or "")
        exit_time = str(payload.get("exit_time_utc") or "")
        if not signal_id or not exit_time or (entry_time and exit_time <= entry_time):
            continue
        r_multiple = float(payload.get("r_multiple") or 0.0)
        mae = float(payload.get("mae") or 0.0)
        mfe = float(payload.get("mfe") or 0.0)
        rows.append(
            {
                "signal_id": signal_id,
                "label_time_utc": exit_time,
                "label_win": 1 if r_multiple > 0 else 0,
                "label_hit_tp": 1 if payload.get("exit_reason") == "TP" else 0,
                "label_expected_r": r_multiple,
                "label_bad_mae": 1 if mae <= mae_threshold_r else 0,
                "label_good_mfe": 1 if mfe >= mfe_threshold_r else 0,
                "label_hold_quality": "GOOD" if r_multiple > 0 else "BAD",
            }
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "labels.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LABEL_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return {
        "mode": "build-ml-labels",
        "labels": len(rows),
        "label_fingerprint": _fingerprint(rows),
        "reports_created": [str(path)],
        "execution_attempted": False,
    }


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()

