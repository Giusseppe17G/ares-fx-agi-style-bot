"""Run matched baselines for a frozen predeclared trend-pullback plan; diagnostics only."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True, help="study inputs.json with relative dataset paths")
    parser.add_argument("--plan", type=Path, required=True, help="frozen plan JSON the datasets must still match")
    parser.add_argument("--output", type=Path, required=True, help="new directory; never overwritten")
    parser.add_argument("--replications", type=int, default=1000)
    args = parser.parse_args(argv)
    package_root = args.source_root.resolve() / "src" / "python"
    if not (package_root / "agi_style_forex_bot_mt5" / "research" / "predeclared_baselines.py").is_file():
        parser.error("source root does not contain the baseline module")
    if args.replications < 1:
        parser.error("replications must be positive")
    sys.path.insert(0, str(package_root))
    from agi_style_forex_bot_mt5.research.experiment_plan import ExperimentPlan
    from agi_style_forex_bot_mt5.research.predeclared_baselines import run_baseline_matrix
    from agi_style_forex_bot_mt5.research.predeclared_runner import canonical_json, current_source_manifest, load_study_inputs
    try:
        inputs = load_study_inputs(args.inputs)
        plan = ExperimentPlan.from_json(args.plan.read_text(encoding="utf-8"))
        args.output.mkdir(parents=True, exist_ok=False)
        report = run_baseline_matrix(plan, inputs["datasets"], replications=args.replications)
        source = current_source_manifest()
        report["baseline_code"] = {"git_commit_sha": source.git_commit_sha, "git_dirty": source.git_dirty,
                                   "source_tree_hash": source.source_tree_hash}
        report["plan_code"] = {"git_commit_sha": plan.to_dict()["code_commit"], "source_sha256": plan.to_dict()["source_sha256"]}
        with (args.output / "baselines.json").open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(report) + "\n")
        with (args.output / "baselines.csv").open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["symbol", "split", "min_score", "strategy_trades", "strategy_net", "strategy_pf",
                             "direction_flip_net", "random_entries_net_p50", "random_entries_share",
                             "random_direction_net_p50", "random_direction_share", "trend_direction_net_p50",
                             "trend_direction_share"])
            for cell in report["cells"]:
                replicated = cell["replicated"]
                writer.writerow([cell["symbol"], cell["split"], cell["min_score"], cell["strategy"]["trades"],
                    round(cell["strategy"]["net_profit"], 2), cell["strategy"]["profit_factor"],
                    round(cell["direction_flip"]["net_profit"], 2),
                    *[value for name in ("random_entries", "random_direction_same_bars", "trend_direction_random_bars")
                      for value in (round(replicated[name]["net_profit"]["p50"], 2),
                                    round(replicated[name]["baseline_at_least_strategy_share"], 4))]])
        print(json.dumps({"status": "COMPLETED", "cells": len(report["cells"]), "plan_id": plan.plan_id,
            "output": str(args.output.resolve()), "promotion_eligible": False, "execution_authorized": False},
            sort_keys=True))
        return 0
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(json.dumps({"status": "REJECTED", "error_type": type(exc).__name__,
            "promotion_eligible": False, "execution_authorized": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
