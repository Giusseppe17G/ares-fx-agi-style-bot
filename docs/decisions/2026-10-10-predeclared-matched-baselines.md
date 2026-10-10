# Matched baselines for the predeclared trend-pullback study

Date: 2026-10-10. Touches: backtesting/research diagnostics only. No strategy,
risk, execution, Expert or production Python behaviour changes. Execution and
promotion stay blocked.

## Context

`docs/testing/next-evidence-protocol.md` requires comparing a strategy with
no-trade, a directional baseline, random entries with equivalent risk,
frequency and costs, and an ablation of its main filter, on identical data and
execution. The predeclared runner records `baselines_status=NOT_EVALUATED`.
The predeclared study (`predeclared-3e9b4d4`) found 25/27 negative cells but
could not say whether the strategy's choices were better or worse than chance.

## Decision

`research/predeclared_baselines.py` (version `predeclared_baselines_v1`):

- **Same eligibility.** `scan_eligible_bars` applies the evaluator's causal
  scoping, warmup, full exit horizon and feature validity. The strategy's own
  evaluated bars must equal this set or the cell fails.
- **Same execution.** Every eligible bar is simulated once as BUY and once as
  SELL with the strategy's `build_signal_prices`, lot, costs, management and
  backtester. `Backtester._simulate_candidate` keeps no state between
  candidates, so the strategy and all baselines are subsets of the same
  outcomes. The strategy subset must reproduce `calculate_metrics` exactly or
  the cell fails; on the preserved data it reproduces the archived metrics.
- **Baselines.** `no_trade`; `direction_flip` (the strategy's bars, opposite
  direction: an ablation of its directional choice); `random_entries` (as many
  random eligible bars as the strategy's closed trades, random direction);
  `random_direction_same_bars` (the strategy's bars, random direction: isolates
  timing from direction); `trend_direction_random_bars` (random bars in the
  EMA20/EMA50 trend direction: a directional baseline without the pullback and
  score filter). Replicated baselines draw without replacement from bars whose
  needed outcomes exist, with a seed derived from version, plan, plan seed,
  cell and baseline name.
- **Statistics.** Per replication: trades, net profit, profit factor (backtester
  definition) and win rate; reported as mean and 5/50/95 percentiles, plus the
  share of draws doing at least as well as the strategy, `(k+1)/(R+1)`.
  Drawdowns are not resampled. There is no correction for the many cells and
  baselines; shares are descriptive, not significance tests.
- **Scope.** Runs on a frozen plan whose dataset bindings must match; records
  both the plan's code identity and the baseline code identity. Development
  data already inspected stays development: nothing becomes a holdout and no
  hypothesis is selected (`NONE_COMPARE_ALL`).

## Limits

Candidates overlap and are not independent observations or a portfolio. Costs,
tick value and spreads are the plan's illustrative assumptions. A strategy that
beat these baselines would only qualify for the next review step of the
Strategy Promotion Gate; one that does not is evidence against its current
selection rules on this development data, not a statement about other data.
