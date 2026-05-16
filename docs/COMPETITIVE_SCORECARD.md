# Competitive Scorecard

The competitive scorecard summarizes whether the bot is approaching the operating standard expected from serious public Forex EAs: multipair testing, realistic costs, robustness, validation beyond in-sample returns, and controlled drawdown.

It does not enable demo execution.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Command

```powershell
$env:PYTHONPATH="src/python"; py -m agi_style_forex_bot_mt5.cli --mode competitive-scorecard --reports-root data\reports --output-dir data\reports\competitive_scorecard
```

## Inputs

The scorecard reads:

- Base backtest summary.
- Walk-forward summary.
- Monte Carlo summary.
- Stress-test summary and scenarios.
- Benchmark summary.

## Metrics

It compares:

- Net return percent.
- Profit factor.
- Max drawdown percent.
- Expectancy R.
- Sharpe and Sortino.
- Winrate.
- Trades count.
- Robustness score.
- Monte Carlo risk.
- Stress survival score.
- Out-of-sample score.
- Cost sensitivity score.
- Baselines beaten.

## Classification

- `COMPETITIVE_CANDIDATE`
- `NEEDS_OPTIMIZATION`
- `WEAK_EDGE`
- `REJECTED`

Hard blocks:

- Cannot be `COMPETITIVE_CANDIDATE` unless at least three baselines are beaten after costs.
- Cannot be `COMPETITIVE_CANDIDATE` if walk-forward OOS is negative.
- Cannot be `COMPETITIVE_CANDIDATE` if Monte Carlo or stress testing fail.
- Cannot be `COMPETITIVE_CANDIDATE` if removing the top `5%` of trades destroys profitability.

This moves the project closer to institutional discipline by requiring evidence quality, not just attractive equity curves.
