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

py -m agi_style_forex_bot_mt5.cli --mode edge-evaluation --runs-root data\runs --run-id 20260517-160651-real-data-research --output-dir data\reports\edge

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

## Artifact Discovery

The evaluator resolves the latest run by run metadata and last-write time. Use `--run-id` to force an exact run when comparing multiple research runs.

Metric fallback order:

1. `reports/backtests/trades.csv`
2. nested `reports/backtests/**/trades.csv`
3. `reports/backtests/summary.json`
4. `final_summary_compact.json`
5. `final_summary.json`

If `trades.csv` is missing but `final_summary_compact.json` says `total_trades=213`, edge evaluation keeps `total_trades=213` and `sample_status=USABLE_SAMPLE`.

## Metrics Status

`FULL_EDGE_METRICS` means trade-level PnL exists and the evaluator can calculate win rate, profit factor, expectancy, drawdown, and grouping metrics.

`COUNTS_ONLY` means the run summary has trade counts, but trade-level PnL or key metrics are missing. This is useful evidence that signal frequency is working, but it is not enough to claim edge.

When metrics are counts-only:

- `global_profit_factor=null`
- `global_expectancy_r=null`
- `global_winrate=null`
- `missing_metrics` lists the unavailable metrics
- the fast decision cannot be `FORWARD_SHADOW_CANDIDATE`
- the decision becomes `NEEDS_FULL_EDGE_METRICS` for usable samples

To repair `COUNTS_ONLY`, verify that `reports/backtests/trades.csv` exists under the selected run and includes profit or R-multiple columns.

## Next Step: Edge Filtering

When `metrics_status=FULL_EDGE_METRICS` but the decision is `TEST_ACTIVE_RESEARCH_ONLY` or global edge is mixed, run:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode edge-filtering --runs-root data\runs --edge-dir data\reports\edge --output-dir data\reports\edge_filtering
```

This creates `BALANCED_FILTERED`, which keeps the safer BALANCED frequency while disabling weak symbols, strategies, sessions, and regimes. It does not enable demo/live trading.

If edge filtering returns `NO_ACTIONABLE_FILTER`, do not use `BALANCED_FILTERED`; compare `BALANCED` against `ACTIVE` in research-only mode instead.

Before trusting profile comparison output, run `profile-threshold-audit` and `profile-integrity`. If ACTIVE and BALANCED are `IDENTICAL_THRESHOLDS`, treat it as a failed config/application bug. If they are `DIFFERENT_THRESHOLDS_IDENTICAL_METRICS`, thresholds are applied but the sample may be insensitive; use BALANCED only after robustness validation and do not use ACTIVE operationally.

When the BALANCED candidate gate returns `BALANCED_NEEDS_ROBUSTNESS_VALIDATION`, run `robustness-fast` to check Monte Carlo, stress, reduced walk-forward and cost sensitivity without a full heavy rerun.

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
- `NEEDS_FULL_EDGE_METRICS`: enough trades exist, but PnL/expectancy metrics are missing.
- `CONTINUE_BALANCED_RESEARCH`: sample is useful but not strong enough for forward-shadow candidate status.
- `TEST_ACTIVE_RESEARCH_ONLY`: try higher signal frequency strictly for research diagnostics.
- `FORWARD_SHADOW_CANDIDATE`: evidence is good enough to continue paper-only forward-shadow observation.
- `NEEDS_STRATEGY_FIX`: global edge is negative or selected strategies are weak.
- `NEEDS_BROKER_COST_FIX`: spread or cost blockers dominate.
- `REJECT_CURRENT_CONFIG`: current configuration should not continue.

No decision can imply demo/live approval.
