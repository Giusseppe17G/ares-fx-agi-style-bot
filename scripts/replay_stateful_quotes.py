"""Offline stateful replay of recorded bid/ask events; never connects to MT5."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--instrument-snapshot", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--initial-balance", type=float, required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--slippage-points", type=float, required=True)
    parser.add_argument("--commission-per-lot-round-turn", type=float, required=True)
    model_group = parser.add_mutually_exclusive_group(required=True)
    model_group.add_argument("--model-dir", type=Path, help="Explicit trusted local model bundle; never a download.")
    model_group.add_argument("--without-ml", action="store_true", help="Requires PAPER_ALLOW_DISABLED_ML=True in research config.")
    args = parser.parse_args(argv)
    package_root = args.source_root.resolve() / "src" / "python"
    if not (package_root / "agi_style_forex_bot_mt5" / "backtesting" / "stateful_replay.py").is_file():
        parser.error("source root does not contain the reviewed stateful replay module")
    sys.path.insert(0, str(package_root))
    from agi_style_forex_bot_mt5.backtesting.stateful_replay import run_stateful_replay
    from agi_style_forex_bot_mt5.backtesting.stateful_replay_io import load_replay_events
    from agi_style_forex_bot_mt5.config import load_config
    from agi_style_forex_bot_mt5.contracts import AccountState
    from agi_style_forex_bot_mt5.core.instruments import InstrumentRegistrySnapshot
    from agi_style_forex_bot_mt5.ml import MLFilter
    from agi_style_forex_bot_mt5.paper_trading.paper_fill_model import PaperFillModel

    if not args.config.is_file():
        parser.error("explicit config file is missing")
    config = load_config(args.config)
    if args.without_ml and not config.paper_allow_disabled_ml:
        parser.error("--without-ml requires PAPER_ALLOW_DISABLED_ML=True")
    model = MLFilter.disabled_for_research() if args.without_ml else MLFilter(args.model_dir)
    if not args.without_ml and model.bundle is None:
        parser.error("explicit model bundle is unavailable or invalid")
    result = run_stateful_replay(
        load_replay_events(args.events), config=config,
        initial_account=AccountState(login=1, trade_mode="DEMO", balance=args.initial_balance,
            equity=args.initial_balance, margin_free=args.initial_balance, currency=args.currency,
            is_demo=True, trade_allowed=True),
        instrument_snapshot=InstrumentRegistrySnapshot.read(args.instrument_snapshot),
        output_dir=args.output_dir, model_filter=model,
        fill_model=PaperFillModel(max_spread_points=config.max_spread_points_default,
            max_tick_age_seconds=config.max_market_snapshot_age_seconds,
            slippage_points=args.slippage_points,
            commission_per_lot_round_turn=args.commission_per_lot_round_turn),
    )
    payload = result.to_dict()
    summary = {key: value for key, value in payload.items() if key not in {"trades", "decisions", "valuations", "rejections"}}
    summary.update(decision_count=len(payload["decisions"]), trade_count=len(payload["trades"]),
                   rejection_count=len(payload["rejections"]), report=str(args.output_dir.resolve() / "result.json"))
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 2 if result.halted or not result.audit_complete else 0


if __name__ == "__main__":
    raise SystemExit(main())
