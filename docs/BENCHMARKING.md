# Benchmarking

Fase 6 compares the strategy ensemble against simple baselines after costs. This helps detect whether the bot has a real edge or is merely matching naive behavior.

No trading is enabled.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Command

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode benchmark --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --data-dir data\historical --report-dir data\reports\benchmarks
```

## Baselines

- `BUY_AND_HOLD_PROXY`
- `RANDOM_ENTRY_WITH_SAME_FREQUENCY`
- `EMA20_EMA50_CROSS`
- `RSI_MEAN_REVERSION_SIMPLE`
- `SESSION_BREAKOUT_SIMPLE`
- `NO_TRADE_BASELINE`

The benchmark runner uses the same backtesting machinery and cost assumptions. If `data/reports/broker_costs/broker_cost_profile.json` exists, p95 spread can be used by CLI-driven backtests/benchmarking where applicable.

## Reports

- `data/reports/benchmarks/summary.json`
- `data/reports/benchmarks/benchmark_results.csv`
- `data/reports/benchmarks/comparison.csv`

## Interpretation

The ensemble must beat at least three simple baselines after costs before it can be considered competitive. If it does not, the result should be `WATCHLIST`, `NEEDS_OPTIMIZATION`, or `REJECTED`.
