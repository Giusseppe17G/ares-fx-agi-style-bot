# Forward Drift Detection

Forward drift detection compares live paper observation against backtest and research evidence.

It is a blocking research control, not an execution permission.

## Drift Types

- `PERFORMANCE_DRIFT`: forward winrate, expectancy, or drawdown materially degrade versus baseline.
- `COST_DRIFT`: real spread/costs are materially worse than the research profile.
- `NEEDS_MORE_DATA`: sample size is too small for a reliable conclusion.
- `REJECT_STRATEGY`: performance drift is severe enough to block the candidate.
- `FORWARD_OK`: no material drift detected with enough sample.

## Inputs

Forward metrics:

- closed paper trades
- winrate
- expectancy R
- max drawdown shadow
- spread statistics
- trade frequency
- rejection reasons

Baseline metrics:

- backtest summary
- research summary
- broker cost profile
- competitive scorecard

## Promotion Impact

Forward drift detection can only block or request more data. It cannot enable demo execution.

Any strategy with severe cost drift, performance drift, or too little forward data remains `WATCHLIST` or `REJECTED`.

