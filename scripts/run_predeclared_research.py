"""Prepare or execute the fixed offline trend-pullback research comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("plan", help="Persist a predeclared plan without evaluating strategy outcomes.")
    prepare.add_argument("--inputs", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run", help="Run every predeclared comparison cell; never select a winner.")
    run.add_argument("--inputs", type=Path, required=True)
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    package_root = args.source_root.resolve() / "src" / "python"
    expected = package_root / "agi_style_forex_bot_mt5" / "research" / "predeclared_runner.py"
    if not expected.is_file():
        parser.error("source root does not contain the predeclared research runner")
    sys.path.insert(0, str(package_root))
    from agi_style_forex_bot_mt5.research.experiment_plan import ExperimentPlan
    from agi_style_forex_bot_mt5.research.predeclared_runner import (
        prepare_study_plan, run_predeclared_research, write_plan_new,
    )
    try:
        prepared, inputs = prepare_study_plan(args.inputs)
        if args.command == "plan":
            write_plan_new(prepared, args.output)
            payload = {"status": "PREDECLARED", "plan_id": prepared.plan_id,
                "plan": str(args.output.resolve()), "evaluations_performed": 0,
                "selection_policy": "NONE_COMPARE_ALL", "promotion_eligible": False,
                "execution_authorized": False}
        else:
            plan = ExperimentPlan.from_json(args.plan.read_text(encoding="utf-8"))
            if prepared.plan_id != plan.plan_id:
                raise ValueError("study inputs or current sources differ from the predeclared plan")
            result = run_predeclared_research(plan, inputs["datasets"], output_dir=args.output,
                dataset_paths=inputs["dataset_paths"])
            report = result.to_dict()
            payload = {key: value for key, value in report.items() if key != "cells"}
            payload["summary"] = str(args.output.resolve() / "summary.json")
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
        return 2 if payload["status"] == "INCOMPLETE" else 0
    except (ValueError, TypeError, OSError) as exc:
        # Configuration/data may contain paths or other private material.
        # Keep CLI failure output structural; no raw values or traceback.
        print(json.dumps({"status": "REJECTED", "error_type": type(exc).__name__,
            "execution_authorized": False, "promotion_eligible": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
