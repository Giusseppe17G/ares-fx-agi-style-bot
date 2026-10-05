"""Re-evaluate preserved candidate PnL; never a portfolio or promotion test."""

from __future__ import annotations

import argparse
from dataclasses import fields
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--diagnostic-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=82)
    parser.add_argument("--iterations", type=int, default=2000)
    args = parser.parse_args()
    root = args.source_root.resolve()
    package = root / "src" / "python"
    if not (package / "agi_style_forex_bot_mt5" / "backtesting" / "monte_carlo.py").is_file():
        parser.error("source-root must contain the project source; no installed-package fallback")
    if args.seed < 0 or args.iterations <= 0:
        parser.error("seed must be nonnegative and iterations positive")
    sys.path.insert(0, str(package))
    os.environ["AGI_FX_PROJECT_ROOT"] = str(root)
    os.environ["AGI_FX_DATA_ROOT"] = str(args.output_dir.resolve() / "runtime")
    import pandas as pd
    from agi_style_forex_bot_mt5.backtesting.backtester import TradeResult
    from agi_style_forex_bot_mt5.backtesting.monte_carlo import run_monte_carlo_report
    from agi_style_forex_bot_mt5.backtesting.stress_tester import run_stress_report
    from agi_style_forex_bot_mt5.core import SafetyEnvelope

    summary_path = args.diagnostic_dir / "summary.json"
    upstream = json.loads(summary_path.read_text(encoding="utf-8"))
    if upstream.get("purpose") != "CORRECTNESS_DIAGNOSTIC_NOT_PROMOTION":
        raise ValueError("expected a preserved correctness diagnostic")
    balance = upstream["settings"]["initial_balance"]
    if isinstance(balance, bool) or not isinstance(balance, (float, int)) or not math.isfinite(balance) or balance <= 0:
        raise ValueError("upstream initial balance must be finite and positive")
    columns = [field.name for field in fields(TradeResult) if field.name != "metadata"]
    prepared, seen = [], set()
    for item in upstream["symbols"]:
        symbol = item["symbol"]
        if not isinstance(symbol, str) or not symbol.isascii() or not symbol.isalpha() or len(symbol) != 6 or symbol in seen:
            raise ValueError("expected unique six-letter FX symbols")
        seen.add(symbol)
        trade_path = args.diagnostic_dir / f"{symbol}_trades.csv"
        frame = pd.read_csv(trade_path)
        if len(frame) != item["metrics"]["trades_total"]:
            raise ValueError(f"trade count differs from preserved summary: {symbol}")
        # Metadata and flattened strategy columns are not consumed by these
        # diagnostics. Do not evaluate Python repr exported by the old CSV writer.
        records = frame.loc[:, columns].to_dict("records")
        prepared.append((symbol, trade_path, records, sorted(set(frame.columns) - set(columns))))
    if not prepared:
        raise ValueError("upstream contains no symbols")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    reports = []
    for symbol, trade_path, records, ignored in prepared:
        mc = run_monte_carlo_report(trades=records, trades_path=trade_path,
            report_dir=args.output_dir / symbol / "monte-carlo", seed=args.seed,
            iterations=args.iterations, initial_balance=balance, method="bootstrap",
            ruin_threshold_pct=30.)
        stress = run_stress_report(trades=records, report_dir=args.output_dir / symbol / "stress",
            initial_balance=balance)
        result = {"symbol": symbol, "trades": len(records),
            "upstream_csv_sha256": sha256(trade_path.read_bytes()).hexdigest(),
            "ignored_non_economic_columns": ignored,
            "monte_carlo_classification": mc["classification"],
            "monte_carlo_drawdown_30pct_probability_pct": mc["probability_of_ruin"],
            "monte_carlo_return_p05_pct": mc["fifth_percentile_return_pct"],
            "monte_carlo_adverse_drawdown_p95_pct": mc["ninety_fifth_percentile_drawdown_pct"],
            "stress_classification": stress["classification"],
            "monte_carlo_manifest": mc["run_manifest"], "stress_manifest": stress["run_manifest"]}
        reports.append(result)
        print(json.dumps({key: value for key, value in result.items() if not key.endswith("manifest")}, allow_nan=False))
    summary = SafetyEnvelope().seal({
        "purpose": "PRESERVED_CANDIDATE_SEQUENCE_DIAGNOSTIC_NOT_PROMOTION",
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "upstream_summary_sha256": sha256(summary_path.read_bytes()).hexdigest(),
        "upstream_code_commit": upstream["base_commit"],
        "upstream_provenance_status": "INTEGRITY_REFERENCED_NOT_BROKER_AUTHENTICATED",
        "dataset_role": upstream["dataset_role"],
        "cost_provenance": upstream["cost_provenance"],
        "assumed_broker_metadata": upstream["assumed_broker_metadata"],
        "seed": args.seed, "iterations": args.iterations, "initial_balance": balance,
        "sampling_model": "IID_FIXED_CURRENCY_PNL_NO_POSITION_RESIZING",
        "aggregate_portfolio_simulated": False, "full_risk_pipeline_applied": False,
        "operationally_eligible": False, "promotion_eligible": False,
        "symbols": reports,
    }, full=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
