# Strategy Research

Fase 7 adds a research layer for versioned strategy candidates, controlled parameter grids, anti-overfit screening, and recommended strategy mixes.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Command

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode research --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --reports-root data\reports --output-dir data\reports\research --max-candidates 100
```

## What It Does

- Loads data quality and broker cost artifacts when present.
- Generates controlled candidates for the six strategy families.
- Backtests candidates offline.
- Runs abbreviated stress checks for candidates.
- Applies `OverfitGuard`.
- Writes a candidate registry and recommended strategy mix.

## Reports

- `data/reports/research/research_summary.json`
- `data/reports/research/research_summary.csv`
- `data/reports/research/candidate_registry.json`
- `data/reports/research/recommended_strategy_mix.json`
- `data/reports/research/rejected_candidates.csv`
- `data/reports/research/ablation_results.csv`
- `data/reports/research/strategy_version_comparison.csv`
- `data/reports/research/report.html`

Candidates are not execution permission. Missing OOS, Monte Carlo, stress, or competitive evidence must remain `WATCHLIST` or `REJECTED`.

## Phase 16 Ablations

Research artifacts now reserve explicit comparisons for:

- Legacy reference strategy version.
- Market-structure upgraded strategy version.
- Without market-structure filters.
- Without cost scoring.
- Without session filters.
- Without liquidity filters.

These reports help identify whether added context improves robustness or merely filters too aggressively.
