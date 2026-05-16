# Stress Testing

Stress testing checks whether a backtest collapses under worse costs, trade concentration, missing data proxies, delayed entries, and artificial loss streaks.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Command

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode stress-test --symbols EURUSD,GBPUSD,USDJPY --data-dir data\historical --report-dir data\reports\stress
```

## Scenarios

The stress runner evaluates:

- Spread multipliers: `x1.0`, `x1.5`, `x2.0`, `x3.0`.
- Slippage multipliers: `x1.0`, `x1.5`, `x2.0`, `x3.0`.
- Commission multipliers: `x1.0`, `x1.5`, `x2.0`.
- Removal of best `1%`, `5%`, and `10%` of trades.
- Artificial losing streaks.
- Missing-bars proxy.
- One-bar entry delay proxy.
- Session shift proxy.

## Reports

Files:

- `data/reports/stress/summary.json`
- `data/reports/stress/scenarios.csv`

## Interpretation

A strategy should not be promoted if spread `x2` destroys profitability or removing the top `5%` of trades removes the whole edge. That usually means the result is too fragile or too concentrated.
