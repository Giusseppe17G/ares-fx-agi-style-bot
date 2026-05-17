# Edge Evaluation

Phase 20 adds a fast read-only decision layer over existing research artifacts. It does not export history, rerun MT5, execute orders, or approve demo/live trading.

Safety remains unchanged:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`
- `order_check was not called`

## Purpose

Use edge evaluation after a `real-data-research` run has already produced backtest and calibration artifacts. It answers quickly:

- which symbols to keep, reduce, watch, or reject
- which strategies belong in `BALANCED`
- which sessions and regimes should be allowed or blocked
- which blockers are useful safety filters versus strategy friction
- whether the current profile should continue research, move to paper-only forward-shadow observation, or go back to strategy work

`FORWARD_SHADOW_CANDIDATE` means paper/shadow observation only. It does not authorize demo execution.

## Commands

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode edge-evaluation --runs-root data\runs --output-dir data\reports\edge

py -m agi_style_forex_bot_mt5.cli --mode symbol-selection --runs-root data\runs --output-dir data\reports\edge

py -m agi_style_forex_bot_mt5.cli --mode strategy-selection --runs-root data\runs --output-dir data\reports\edge
```

## Inputs

The evaluator reads what already exists under the latest run:

- `final_summary_compact.json`
- `reports/backtests/trades.csv`
- `reports/backtests/summary.json`
- `reports/research/research_summary.json`
- `reports/research/research_summary.csv`
- `reports/benchmarks/summary.json`
- `reports/competitive_scorecard/*`
- `reports/calibration/*`
- `reports/strategy_diagnostics/**/*`

Missing optional artifacts are tolerated. Missing or empty `trades.csv` returns `NEEDS_TRADES`.

## Outputs

Reports are written to `data/reports/edge` unless another output directory is provided:

- `edge_summary.json`
- `edge_summary.csv`
- `by_symbol.csv`
- `by_strategy.csv`
- `by_session.csv`
- `by_regime.csv`
- `blockers.csv`
- `recommendations.json`
- `report.html`
- `config_suggestions/balanced_filtered.ini`
- `config_suggestions/research_active.ini`

`balanced_filtered.ini` keeps risk and safety unchanged while suggesting symbols, strategies, and sessions to continue testing. `research_active.ini` is marked `NOT FOR DEMO/LIVE EXECUTION`.

## Decisions

- `NEEDS_MORE_TRADES`: fewer than 30 closed simulated trades.
- `CONTINUE_BALANCED_RESEARCH`: sample is useful but not strong enough for forward-shadow candidate status.
- `TEST_ACTIVE_RESEARCH_ONLY`: try higher signal frequency strictly for research diagnostics.
- `FORWARD_SHADOW_CANDIDATE`: evidence is good enough to continue paper-only forward-shadow observation.
- `NEEDS_STRATEGY_FIX`: global edge is negative or selected strategies are weak.
- `NEEDS_BROKER_COST_FIX`: spread or cost blockers dominate.
- `REJECT_CURRENT_CONFIG`: current configuration should not continue.

No decision can imply demo/live approval.
