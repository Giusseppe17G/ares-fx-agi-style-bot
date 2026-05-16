# Paper Vs Backtest Calibration

Paper-vs-backtest calibration compares forward paper results against offline assumptions.

It answers:

- Did paper expectancy degrade versus backtest?
- Did paper winrate degrade?
- Were observed spreads higher than backtest costs?
- Is trade frequency drifting?
- Are ambiguous fill events common?
- Is the backtest too optimistic for promotion?

## Classifications

- `CALIBRATED_OK`
- `NEEDS_MORE_FORWARD_DATA`
- `BACKTEST_TOO_OPTIMISTIC`
- `COST_ASSUMPTION_TOO_LOW`
- `STRATEGY_BEHAVIOR_DRIFT`
- `REJECT_FOR_PROMOTION`

If calibration returns `BACKTEST_TOO_OPTIMISTIC` or `COST_ASSUMPTION_TOO_LOW`, validation cannot approve the strategy for future promotion.

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode paper-vs-backtest --reports-root data\reports --sqlite data\sqlite\forward-shadow.sqlite3 --output-dir data\reports\paper_vs_backtest
```

Outputs:

- `summary.json`
- `by_symbol.csv`
- `by_strategy.csv`
- `by_regime.csv`
- `report.html`

This mode is diagnostic only and cannot enable demo or live execution.

