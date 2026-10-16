"""Command line for the predeclared daily FX study (research only).

    python -m agi_style_forex_bot_mt5.research.daily_fx.runner freeze \\
        --prices data/historical/fred/daily.csv --rates data/historical/oecd/short-term-interest.csv \\
        --plan-file docs/research/daily_fx_slow_premia_v1/plan.json
    python -m agi_style_forex_bot_mt5.research.daily_fx.runner development ... \\
        --ledger docs/research/daily_fx_slow_premia_v1/ledger.jsonl \\
        --output docs/research/daily_fx_slow_premia_v1/development.json
    python -m agi_style_forex_bot_mt5.research.daily_fx.runner holdout ... \\
        --development docs/research/daily_fx_slow_premia_v1/development.json \\
        --output docs/research/daily_fx_slow_premia_v1/holdout.json

Exit codes: 0 done, 2 invalid arguments or a refused run (plan, data or
engine mismatch, holdout already scored, existing output).
Nothing here reads a terminal, the network or sends an order.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from ..trial_registry import TrialLedger
from .data import load_fred_daily, load_oecd_rates
from .plans import G10_VS_USD, slow_premia_v1
from .study import StudyPlan, run_development, run_holdout

PLANS = {"slow_premia_v1": slow_premia_v1}


def _plan(args: argparse.Namespace):
    panel = load_fred_daily(args.prices, G10_VS_USD)
    rates, rates_sha256 = load_oecd_rates(args.rates, G10_VS_USD)
    plan: StudyPlan = PLANS[args.plan](panel.source_sha256, rates_sha256)
    return plan, panel, rates, rates_sha256


def _frozen_matches(plan: StudyPlan, plan_file: Path) -> None:
    frozen = json.loads(plan_file.read_text(encoding="utf-8"))
    if frozen.get("plan_hash") != plan.plan_hash() or frozen.get("plan") != json.loads(plan.canonical_json()):
        raise ValueError("the plan rebuilt from code and data differs from the frozen plan file")


def _write_new(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=float)
        handle.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Predeclared daily FX study (research only)")
    parser.add_argument("phase", choices=("freeze", "development", "holdout"))
    parser.add_argument("--plan", choices=sorted(PLANS), default="slow_premia_v1")
    parser.add_argument("--prices", required=True, type=Path, help="datasets/exchange-rates data/daily.csv")
    parser.add_argument("--rates", required=True, type=Path, help="OECD short-term-interest.csv")
    parser.add_argument("--plan-file", required=True, type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--development", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        plan, panel, rates, rates_sha256 = _plan(args)
        if args.phase == "freeze":
            _write_new(args.plan_file, {"plan_hash": plan.plan_hash(), "plan": plan.to_dict()})
            print(json.dumps({"phase": "freeze", "plan_hash": plan.plan_hash(), "plan_file": str(args.plan_file)}))
            return 0
        if args.ledger is None or args.output is None:
            raise ValueError("--ledger and --output are required")
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite {args.output}")
        _frozen_matches(plan, args.plan_file)
        ledger = TrialLedger(args.ledger)
        if args.phase == "development":
            summary = run_development(plan, panel, rates, rates_sha256, ledger)
            _write_new(args.output, summary)
        else:
            if args.development is None:
                raise ValueError("--development is required for the holdout")
            development = json.loads(args.development.read_text(encoding="utf-8"))
            summary = run_holdout(plan, panel, rates, rates_sha256, development, ledger, args.output)
        verdicts = {item["hypothesis_id"]: item.get("verdict", item.get("proceed_to_holdout"))
                    for item in summary["hypotheses"]}
        print(json.dumps({"phase": args.phase, "plan_hash": plan.plan_hash(), "results": verdicts}))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"phase": args.phase, "error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
