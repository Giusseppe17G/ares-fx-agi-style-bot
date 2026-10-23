"""Command line for the predeclared daily FX study (research only).

    python -m agi_style_forex_bot_mt5.research.daily_fx.runner freeze \\
        --prices data/historical/fred/daily.csv --rates data/historical/oecd/short-term-interest.csv \\
        --plan-file docs/research/daily_fx_slow_premia_v1/plan.json
    python -m agi_style_forex_bot_mt5.research.daily_fx.runner development <same arguments> \\
        --ledger docs/research/trial_ledger.jsonl
    python -m agi_style_forex_bot_mt5.research.daily_fx.runner holdout <same arguments> \\
        --ledger docs/research/trial_ledger.jsonl
    python -m agi_style_forex_bot_mt5.research.daily_fx.runner freeze --plan real_value_v2 \\
        --prices data/historical/fred/daily.csv --inflation data/historical/worldbank/cpi.csv \\
        --plan-file docs/research/daily_fx_real_value_v2/plan.json

Each plan names the second input it needs: OECD rates (``--rates``) or World
Bank annual CPI inflation (``--inflation``).

Results are always written next to the plan file (development.json,
holdout.json) and never overwritten: an existing holdout.json refuses the
holdout even if the ledger lost its last line. Every plan must use the same
shared ledger, which is committed after each phase, so that no plan can
reuse dates another plan already scored.

Exit codes: 0 done, 2 invalid arguments or a refused run (plan, data,
engine or environment mismatch, holdout already scored, existing output).
Nothing here reads a terminal, the network or sends an order.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Callable, Sequence

import pandas as pd

from ..trial_registry import TrialLedger
from .data import PricePanel, load_fred_daily, load_oecd_rates, load_worldbank_inflation
from .plans import (G10_VS_USD, REAL_VALUE_CURRENCIES, REAL_VALUE_PRICE_START, real_value_v2,
    slow_premia_v1)
from .study import StudyPlan, run_development, run_holdout


@dataclass(frozen=True)
class PlanSpec:
    build: Callable[[str, str], StudyPlan]  # (price sha256, second input sha256) -> plan
    currencies: tuple[str, ...]
    second_input: str  # "rates" or "inflation"
    price_start: str | None = None


PLANS = {
    "slow_premia_v1": PlanSpec(slow_premia_v1, G10_VS_USD, "rates"),
    "real_value_v2": PlanSpec(real_value_v2, REAL_VALUE_CURRENCIES, "inflation", REAL_VALUE_PRICE_START),
}


@dataclass(frozen=True)
class Inputs:
    plan: StudyPlan
    panel: PricePanel
    rates: pd.DataFrame | None = None
    rates_sha256: str | None = None
    inflation: pd.DataFrame | None = None
    inflation_sha256: str | None = None


def _plan(args: argparse.Namespace) -> Inputs:
    spec = PLANS[args.plan]
    if getattr(args, spec.second_input) is None:
        raise ValueError(f"--{spec.second_input} is required by plan {args.plan}")
    panel = load_fred_daily(args.prices, spec.currencies, start=spec.price_start)
    if spec.second_input == "rates":
        rates, rates_sha256 = load_oecd_rates(args.rates, spec.currencies)
        return Inputs(spec.build(panel.source_sha256, rates_sha256), panel, rates, rates_sha256)
    inflation, inflation_sha256 = load_worldbank_inflation(args.inflation, spec.currencies)
    return Inputs(spec.build(panel.source_sha256, inflation_sha256), panel, inflation=inflation,
                  inflation_sha256=inflation_sha256)


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
    parser.add_argument("--rates", type=Path, help="OECD short-term-interest.csv (plans that need rates)")
    parser.add_argument("--inflation", type=Path, help="datasets/cpi data/cpi.csv (plans that need inflation)")
    parser.add_argument("--plan-file", required=True, type=Path)
    parser.add_argument("--ledger", type=Path, help="the shared trial ledger (development and holdout)")
    args = parser.parse_args(argv)
    try:
        inputs = _plan(args)
        plan = inputs.plan
        if args.phase == "freeze":
            _write_new(args.plan_file, {"plan_hash": plan.plan_hash(), "plan": plan.to_dict()})
            print(json.dumps({"phase": "freeze", "plan_hash": plan.plan_hash(), "plan_file": str(args.plan_file)}))
            return 0
        if args.ledger is None:
            raise ValueError("--ledger is required")
        folder = args.plan_file.parent
        development_file, holdout_file = folder / "development.json", folder / "holdout.json"
        _frozen_matches(plan, args.plan_file)
        ledger = TrialLedger(args.ledger)
        if args.phase == "development":
            if development_file.exists():
                raise FileExistsError(f"refusing to overwrite {development_file}")
            summary = run_development(plan, inputs.panel, inputs.rates, inputs.rates_sha256, ledger,
                                      inputs.inflation, inputs.inflation_sha256)
            _write_new(development_file, summary)
        else:
            if holdout_file.exists():
                raise FileExistsError(f"{holdout_file} exists: the holdout was already scored")
            development = json.loads(development_file.read_text(encoding="utf-8"))
            summary = run_holdout(plan, inputs.panel, inputs.rates, inputs.rates_sha256, development, ledger,
                                  holdout_file, inputs.inflation, inputs.inflation_sha256)
        verdicts = {item["hypothesis_id"]: item.get("verdict", item.get("proceed_to_holdout"))
                    for item in summary["hypotheses"]}
        print(json.dumps({"phase": args.phase, "plan_hash": plan.plan_hash(), "results": verdicts}))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"phase": args.phase, "error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
