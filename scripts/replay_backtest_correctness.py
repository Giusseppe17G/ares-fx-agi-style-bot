"""Offline correctness diagnostic; never an execution or promotion command."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY")
    args = parser.parse_args()
    package_root = args.source_root.resolve() / "src" / "python"
    sys.path.insert(0, str(package_root))
    from agi_style_forex_bot_mt5.backtesting.backtester import (
        ENGINE_VERSION, BacktestSettings, CostModel, load_historical_csv, run_strategy_backtest,
    )
    from agi_style_forex_bot_mt5.config import BotConfig
    from agi_style_forex_bot_mt5.core import SafetyEnvelope
    from agi_style_forex_bot_mt5.core.instruments import assumed_fx_spec
    from agi_style_forex_bot_mt5.strategy.strategy_ensemble import STRATEGY_VERSION

    # New output only: preserve previous historical reports.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source_hash = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        source_hash.update(path.relative_to(package_root).as_posix().encode())
        source_hash.update(path.read_bytes())
    config = BotConfig()
    settings = BacktestSettings(
        run_id="correctness_diagnostic", code_commit=args.code_commit,
        strategy_name="strategy_ensemble", strategy_version=STRATEGY_VERSION, cost_model=CostModel(
            slippage_points=1.0, commission_per_lot_round_turn=7.0,
        ), max_bars_in_trade=96, break_even_trigger_r=0.6,
        trailing_start_r=0.8, trailing_distance_points=80, random_seed=82,
    )
    reports = []
    for symbol in args.symbols.split(","):
        symbol = symbol.strip().upper()
        if not symbol.isalpha() or len(symbol) != 6:
            raise ValueError("diagnostic requires six-letter FX symbols")
        path = args.data_dir / (symbol + "_M5.csv")
        frame, quality = load_historical_csv(path, symbol=symbol, timeframe="M5")
        instrument = assumed_fx_spec(symbol)
        outcome = run_strategy_backtest(
            frame, symbol=symbol, timeframe="M5", config=config,
            settings=settings, instrument=instrument,
        )
        outcome.trades_frame().to_csv(args.output_dir / (symbol + "_trades.csv"), index=False)
        metrics = asdict(outcome.metrics)
        reports.append({
            "symbol": symbol, "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "data_quality": asdict(quality), "instrument": instrument.as_dict(),
            "metrics": metrics, "rejected_count": len(outcome.rejected_candidates),
            "rejection_reasons": dict(Counter(item["reason"] for item in outcome.rejected_candidates)),
        })
    report = SafetyEnvelope().seal({
        "purpose": "CORRECTNESS_DIAGNOSTIC_NOT_PROMOTION",
        "base_commit": args.code_commit, "source_tree_sha256": source_hash.hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "engine_version": ENGINE_VERSION, "signal_profile": config.signal_profile,
        "settings": asdict(settings),
        "assumed_broker_metadata": True,
        "cost_provenance": "ILLUSTRATIVE_NOT_BROKER_VERIFIED",
        "full_risk_pipeline_applied": False, "operationally_eligible": False,
        "symbols": reports,
    }, full=True)

    def finite_json(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {key: finite_json(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [finite_json(item) for item in value]
        return value

    (args.output_dir / "summary.json").write_text(
        json.dumps(finite_json(report), indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    for result in reports:
        print(json.dumps({
            "symbol": result["symbol"], "trades": result["metrics"]["trades_total"],
            "win_rate_pct": result["metrics"]["win_rate_pct"],
            "expectancy": result["metrics"]["expectancy"],
            "rejected": result["rejected_count"], "operationally_eligible": False,
        }))


if __name__ == "__main__":
    main()
