"""Convert already-inspected MT5 export CSVs to the declared research protocol.

This never evaluates outcomes, discovers credentials, fetches prices, or opens
a terminal. All cost/instrument defaults are explicit illustrative assumptions.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import sys


SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")
RAW_FIELDS = {"time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume", "timestamp_utc"}


def prepare(source_dir: Path, output_dir: Path):
    import pandas as pd
    from agi_style_forex_bot_mt5.backtesting.backtester import CostModel
    from agi_style_forex_bot_mt5.core.instruments import assumed_fx_spec
    from agi_style_forex_bot_mt5.research.experiment_plan import (
        ResearchManagement, dataframe_sha256, normalize_research_bars,
    )

    # Validate the complete input set before creating any output.
    items = {}
    for symbol in SYMBOLS:
        path = source_dir / f"{symbol}_M5.csv"
        raw_bytes = path.read_bytes()
        raw_text = raw_bytes.decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(raw_text)), ())
        if len(header) != len(set(header)) or set(header) != RAW_FIELDS:
            raise ValueError("unexpected historical export columns")
        frame = pd.read_csv(io.StringIO(raw_text), float_precision="round_trip")
        # Both supplied clocks must explicitly agree. No timezone inference,
        # sorting, duplicate removal, interpolation or spread repair.
        if not frame["time"].equals(frame["timestamp_utc"]):
            raise ValueError("export timestamp columns disagree")
        canonical = frame[["timestamp_utc", "open", "high", "low", "close", "tick_volume", "spread"]].rename(
            columns={"tick_volume": "volume", "spread": "spread_points"})
        normalized = normalize_research_bars(canonical, symbol=symbol)
        times = normalized["timestamp_utc"]
        gaps = times.diff().dt.total_seconds().dropna()
        zero_count = int((normalized["spread_points"] == 0).sum())
        spec = assumed_fx_spec(symbol)
        costs = CostModel(slippage_points=1, commission_per_lot_round_turn=7).with_instrument(spec)
        item = {
            "path": f"{symbol}_M5.csv", "provider": "EXISTING_MT5_EXPORT_ORIGIN_NOT_AUTHENTICATED",
            "tick_value_currency": "USD", "tick_value_status": "ASSUMED",
            "instrument": spec.as_dict(), "cost_model": asdict(costs),
            "cost_provenance": {"source": "ILLUSTRATIVE_PREDECLARED_V1", "status": "ASSUMED",
                "commission_currency": "USD", "swap_mode": "NOT_MODELED", "assumptions": [
                    "Bar spreads preserved including zero; no broker cost verification",
                    "One point fixed adverse slippage; 7 USD commission per lot round turn",
                    "Fixed illustrative tick value 1 USD per tick per lot; no dynamic FX conversion",
                    "OHLC interpreted as midpoint; observed bid/ask and exit spread unavailable",
                ]},
            "quality_report": {"status": "INSPECTED_DEVELOPMENT_UNVERIFIED_ORIGIN",
                "original_source_file": path.name, "original_source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "transformation": "SELECT_RENAME_ONLY_ROUND_TRIP_FLOATS_NO_ROW_REORDER_OR_REPAIR",
                "rows": len(normalized), "duplicates": 0, "discarded_rows": 0,
                "timezone": "EXPLICIT_OFFSET_CONVERTED_TO_UTC_NOT_INDEPENDENTLY_AUTHENTICATED",
                "first_utc": times.iloc[0].isoformat(), "last_utc": times.iloc[-1].isoformat(),
                "gap_count_over_300_seconds": int((gaps > 300).sum()),
                "largest_gap_seconds": float(gaps.max()) if len(gaps) else 0,
                "zero_spread_rows": zero_count, "zero_spread_pct": zero_count / len(normalized) * 100,
                "coverage": "NOT_VERIFIED_AGAINST_BROKER_SESSION_CALENDAR", "dst": "NOT_VERIFIED",
                "weekend_rows": int((times.dt.dayofweek >= 5).sum()),
                "cost_verified": False, "source_authenticity_verified": False,
                "news_labels": "NOT_AVAILABLE", "final_holdout": "NOT_AVAILABLE"},
        }
        items[symbol] = (normalized, item)
    output_dir.mkdir(parents=True, exist_ok=False)
    datasets = {}
    for symbol, (normalized, item) in items.items():
        target = output_dir / item["path"]
        normalized.drop(columns=["symbol", "timeframe"]).to_csv(target, index=False, mode="x")
        reread = pd.read_csv(target, float_precision="round_trip")
        if dataframe_sha256(reread, symbol=symbol) != dataframe_sha256(normalized, symbol=symbol):
            raise ValueError("canonical CSV round trip changed effective data")
        datasets[symbol] = item
    payload = {"data_role": "DEVELOPMENT_DIAGNOSTIC_ALREADY_INSPECTED", "denomination_currency": "USD",
        "lot": 0.1, "initial_balance": 10000, "random_seed": 82,
        "management": asdict(ResearchManagement()), "datasets": datasets}
    with (output_dir / "inputs.json").open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False)
    return output_dir / "inputs.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    package = args.source_root.resolve() / "src" / "python"
    if not (package / "agi_style_forex_bot_mt5" / "research" / "experiment_plan.py").is_file():
        parser.error("explicit source root must contain research implementation")
    sys.path.insert(0, str(package))
    path = prepare(args.data_dir.resolve(), args.output_dir.resolve())
    print(json.dumps({"status": "INPUTS_PREPARED_NO_EVALUATION", "inputs": str(path),
        "data_role": "DEVELOPMENT_DIAGNOSTIC_ALREADY_INSPECTED", "execution_authorized": False}))


if __name__ == "__main__":
    main()
