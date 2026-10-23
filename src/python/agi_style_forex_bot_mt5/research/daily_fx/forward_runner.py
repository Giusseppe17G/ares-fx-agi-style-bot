"""Command line for forward paper tracking of a frozen daily FX book (research only).

    python -m agi_style_forex_bot_mt5.research.daily_fx.forward_runner freeze \\
        --plan-file docs/research/daily_fx_value_forward_v1/plan.json
    python -m agi_style_forex_bot_mt5.research.daily_fx.forward_runner fetch-inflation \\
        --output data/historical/worldbank/inflation-20261101.csv
    python -m agi_style_forex_bot_mt5.research.daily_fx.forward_runner run \\
        --plan-file docs/research/daily_fx_value_forward_v1/plan.json --prices-dir data/historical \\
        --inflation-base data/historical/worldbank/cpi.csv \\
        --inflation-supplement data/historical/worldbank/inflation-20261101.csv \\
        --swap-snapshots-dir data/runtime --ledger data/runtime/forward/value_forward_v1.jsonl

``fetch-inflation`` is the only network call: an HTTPS GET of the World Bank
API (indicator FP.CPI.TOTL.ZG, the ten series), written to a new CSV plus a
sidecar JSON. ``run`` reads local files only. It appends a checkpoint to the
ledger when the record advances, and prints the status as JSON.

Exit codes:

- 0: done.
- 2: refused or invalid input. Examples: the plan or the engine differ from
  the frozen file, the broker history changed after the fact, the data are
  missing or too short, or the output exists.
- 3: the World Bank download failed.

Nothing here reads a terminal or sends an order.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence
import urllib.error

from ..trial_registry import TrialLedger
from .data import load_worldbank_inflation
from .forward import (ForwardPlan, ForwardRefused, fetch_world_bank_inflation, load_broker_daily,
    read_inflation_supplement, run_forward)
from .plans import value_forward_v1

PLANS = {"value_forward_v1": value_forward_v1}


def _write_new(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=float)
        handle.write("\n")


def _frozen(plan: ForwardPlan, plan_file: Path) -> None:
    frozen = json.loads(plan_file.read_text(encoding="utf-8"))
    if frozen.get("plan_hash") != plan.plan_hash() or frozen.get("plan") != json.loads(plan.canonical_json()):
        raise ForwardRefused("PLAN_MISMATCH", "the plan rebuilt from code differs from the frozen plan file "
                             "(code or engine changed)")


def _snapshots(directory: Path | None) -> tuple[list[dict], list[str]]:
    from ...broker_swap_snapshot import read_swap_snapshot

    if directory is None:
        return [], []
    loaded, skipped = [], []
    for path in sorted(directory.glob("swap_snapshot-*.json")):
        try:
            loaded.append(read_swap_snapshot(path))
        except Exception:  # an unreadable or altered snapshot only lowers the swap coverage
            skipped.append(path.name)
    return loaded, skipped


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forward paper tracking of a frozen daily FX book (research only)")
    parser.add_argument("phase", choices=("freeze", "fetch-inflation", "run"))
    parser.add_argument("--plan", choices=sorted(PLANS), default="value_forward_v1")
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--output", type=Path, help="fetch-inflation: new CSV path")
    parser.add_argument("--first-year", type=int, default=2020, help="fetch-inflation: first year")
    parser.add_argument("--last-year", type=int, default=datetime.now(timezone.utc).year, help="fetch-inflation")
    parser.add_argument("--prices-dir", type=Path, help="run: folder with the <SYMBOL>_D1.csv exports")
    parser.add_argument("--inflation-base", type=Path, help="run: datasets/cpi data/cpi.csv (pinned)")
    parser.add_argument("--inflation-supplement", type=Path, help="run: CSV written by fetch-inflation")
    parser.add_argument("--swap-snapshots-dir", type=Path, help="run: folder with swap_snapshot-*.json files")
    parser.add_argument("--ledger", type=Path, help="run: the forward ledger (kept and backed up)")
    args = parser.parse_args(argv)
    try:
        if args.phase == "fetch-inflation":
            if args.output is None:
                raise ValueError("--output is required")
            try:
                meta = fetch_world_bank_inflation(args.output, args.first_year, args.last_year)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                print(json.dumps({"phase": args.phase, "error": f"download failed: {type(error).__name__}"}),
                      file=sys.stderr)
                return 3
            print(json.dumps({"phase": args.phase, "output": str(args.output), **meta}))
            return 0
        plan = PLANS[args.plan]()
        if args.plan_file is None:
            raise ValueError("--plan-file is required")
        if args.phase == "freeze":
            _write_new(args.plan_file, {"plan_hash": plan.plan_hash(), "plan": plan.to_dict()})
            print(json.dumps({"phase": "freeze", "plan_hash": plan.plan_hash(), "plan_file": str(args.plan_file)}))
            return 0
        missing = [name for name in ("prices_dir", "inflation_base", "ledger") if getattr(args, name) is None]
        if missing:
            raise ValueError("required: " + ", ".join("--" + name.replace("_", "-") for name in missing))
        _frozen(plan, args.plan_file)
        panel = load_broker_daily(args.prices_dir, plan.currencies, plan.price_start)
        base, base_sha256 = load_worldbank_inflation(args.inflation_base, plan.currencies)
        supplement = (read_inflation_supplement(args.inflation_supplement, plan.currencies)[0]
                      if args.inflation_supplement is not None else None)
        snapshots, skipped = _snapshots(args.swap_snapshots_dir)
        summary = run_forward(plan, panel, base, base_sha256, supplement, snapshots, TrialLedger(args.ledger))
        summary["swap_snapshots_skipped"] = skipped
        print(json.dumps(summary, indent=2, sort_keys=True, default=float))
        return 0
    except ForwardRefused as error:
        print(json.dumps({"phase": args.phase, "refused": error.code, "error": str(error)}), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"phase": args.phase, "error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
