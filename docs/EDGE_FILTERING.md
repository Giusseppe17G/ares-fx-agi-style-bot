# Edge Filtering

Phase 21 turns a broad `BALANCED` research profile into a narrower `BALANCED_FILTERED` profile using already generated edge reports.

This phase is research/backtest/paper-only:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- no `order_send`
- no `order_check`

`BALANCED_FILTERED` does not approve demo/live execution and does not promote a weak global configuration to forward-shadow by itself.

## Commands

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode edge-filtering --runs-root data\runs --edge-dir data\reports\edge --output-dir data\reports\edge_filtering

py -m agi_style_forex_bot_mt5.cli --mode build-filtered-profile --runs-root data\runs --edge-dir data\reports\edge --output-dir data\reports\edge_filtering --base-profile BALANCED
```

Rerun research with the filtered profile:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode real-data-research --symbols EURUSD,GBPUSD,USDJPY --bars 20000 --output-root data\runs --signal-profile BALANCED_FILTERED --profile-config data\reports\edge_filtering\balanced_filtered.ini --quick
```

## Inputs

The builder reads:

- `data/reports/edge/edge_summary.json`
- `data/reports/edge/by_symbol.csv`
- `data/reports/edge/by_strategy.csv`
- `data/reports/edge/by_session.csv`
- `data/reports/edge/by_regime.csv`
- `data/reports/edge/blockers.csv`
- latest run `final_summary_compact.json`

## Outputs

- `filter_summary.json`
- `by_symbol_filter.csv`
- `by_strategy_filter.csv`
- `by_session_filter.csv`
- `by_regime_filter.csv`
- `balanced_filtered.ini`
- `balanced_filtered.json`
- `filter_diff.json`
- `research_active_experiment.ini`
- `report.html`

## Filtering Decisions

Phase 21B prevents an empty filtered profile from looking useful.

Possible `filtering_decision` values:

- `ACTIONABLE_FILTER_CREATED`: at least one symbol, strategy, session, regime, or setup-quality rule changed.
- `NO_ACTIONABLE_FILTER`: all evidence is watchlist or inconclusive; do not apply `BALANCED_FILTERED`.
- `NEEDS_MORE_EDGE_METRICS`: trade counts exist but PnL/expectancy metrics are missing.
- `ACTIVE_RESEARCH_EXPERIMENT_RECOMMENDED`: BALANCED is mixed and no clean filtered subset exists; test ACTIVE only in research.
- `REJECT_BALANCED_PROFILE`: global BALANCED edge is negative and no positive subset was found.

If `filtering_decision != ACTIONABLE_FILTER_CREATED`, `balanced_filtered.ini` is generated with:

```ini
APPLY_FILTERS=false
NOT_FOR_DEMO_LIVE=true
```

`real-data-research --signal-profile BALANCED_FILTERED` records `FILTERED_PROFILE_NOT_ACTIONABLE` when the supplied profile config is not actionable.

## Rules

Symbols:

- `KEEP`: at least 30 trades, `profit_factor >= 1.10`, and `expectancy_r > 0`.
- `WATCHLIST`: enough activity but incomplete or near break-even metrics.
- `DISABLE`: negative expectancy, weak profit factor, or excessive drawdown.

Strategies:

- `KEEP`: enough trades with positive edge metrics.
- `WATCHLIST`: near break-even or missing metrics.
- `DISABLE_IN_BALANCED`: weak strategy with sufficient sample.
- `RESEARCH_ONLY`: insufficient sample.

Sessions and regimes:

- `ROLLOVER` is blocked if spread/cost blockers dominate or expectancy is negative.
- Any session/regime with sufficient sample and negative expectancy is blocked.
- High volatility can be blocked when cost blockers dominate.

Setup quality:

- D-quality setups are disabled by default.
- Spread and cost guards remain strict.
- Filtered thresholds are suggestions for research reruns, not risk relaxation.

## Interpretation

`BALANCED_FILTERED` should reduce noise and retest the promising parts of `BALANCED`. Compare the next run against the original `BALANCED` run before considering any paper-only forward-shadow expansion.

When `ACTIVE_RESEARCH_EXPERIMENT_RECOMMENDED`, use `research_active_experiment.ini` only with quick research or profile comparison. ACTIVE remains `NOT_FOR_DEMO_LIVE=true` and cannot promote to forward-shadow or demo/live.
