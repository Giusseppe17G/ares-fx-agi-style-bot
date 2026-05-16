# Strategy Promotion Gate

This gate prevents a strategy or symbol from moving forward based on weak or overfit evidence.

It does not enable real trading, demo execution, or broker order submission.

Mandatory safety context:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

## Classifications

`APPROVED_FOR_SHADOW_OBSERVATION`

The symbol/strategy has enough statistical evidence to consider longer read-only shadow observation.

`WATCHLIST`

Some core metrics are promising, but required evidence is incomplete. This is common when sample size, out-of-sample validation, Monte Carlo, or cost sensitivity is missing.

`REJECTED`

Core evidence is not acceptable. The strategy/symbol should not move forward.

## Minimum Requirements

A strategy or symbol can only be considered for `APPROVED_FOR_SHADOW_OBSERVATION` when it satisfies:

- Minimum `300` trades in backtest, or a written statistical justification for a smaller sample.
- Profit factor greater than `1.25`.
- Maximum drawdown below `12%`.
- Expectancy R greater than `0`.
- Positive out-of-sample result.
- No dependence on one or two unusually large trades.
- Results not concentrated in a single week.
- Monte Carlo does not show excessive risk of ruin.
- Reasonable sensitivity to spread and slippage stress.
- Walk-forward test windows are positive and not materially worse than train/validation windows.
- Stress test remains viable under spread `x2`.
- Removing the top `5%` of trades does not destroy the full edge.
- Results are not excessively concentrated by hour, weekday, session, regime, or week.

## Anti-Overfitting Rules

- Do not optimize parameters until every symbol passes baseline validation.
- Do not choose a symbol only because it had one large winner.
- Do not accept a result concentrated in one week, one session, or one regime.
- Do not raise spread or tick-age limits to make backtests or data reads pass.
- Treat all backtest evidence as research, not execution permission.

## Required Reproducibility

Every report must be reproducible from:

- Config values.
- Commit or code version.
- Symbol list.
- Timeframe.
- Historical CSV files.
- Data fingerprint.
- Date range.
- Spread, slippage, commission, SL/TP, break-even, trailing, and time-stop settings.

## Gate Output

The Phase 4 backtester writes Strategy Promotion Gate results into:

- `data/reports/backtests/summary.json`
- `data/reports/backtests/summary.csv`
- `data/reports/backtests/report.html`

Promotion only allows further shadow observation. It does not authorize demo or live execution.

## Phase 5 Required Evidence

From Phase 5 onward, a symbol/strategy can only be classified as `APPROVED_FOR_SHADOW_OBSERVATION` when all validation layers are acceptable:

- Base backtest meets sample, profit factor, expectancy, and drawdown minimums.
- Walk-forward test results are positive out-of-sample.
- Monte Carlo risk of ruin is not excessive.
- Stress testing does not collapse under spread `x2`.
- Removing the top `5%` of trades does not eliminate all profitability.
- No single hour, day, session, regime, or week explains the result.

If any layer is missing, inconclusive, or impossible to calculate, the final decision must be `WATCHLIST` or `REJECTED`.
