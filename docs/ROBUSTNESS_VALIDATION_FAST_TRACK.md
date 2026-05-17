# Robustness Validation Fast Track

Phase 23 validates a positive BALANCED profile without rerunning the full 50,000-bar pipeline. It consumes existing research artifacts and remains paper/shadow-only.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- no `order_send`
- no `order_check`

`PAPER_FORWARD_SHADOW_CANDIDATE` means the profile may continue paper-only forward-shadow observation. It is not demo/live approval.

## Command

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode robustness-fast --runs-root data\runs --profile-runs-dir data\reports\profile_runs --profile BALANCED --output-dir data\reports\robustness
```

## Inputs

The runner prefers trade-level evidence:

1. `data/runs/<run_id>/reports/backtests/trades.csv`
2. nested `reports/backtests/**/trades.csv`
3. `data/reports/profile_runs/balanced/trades.csv`
4. profile comparison summary metrics as limited fallback

If only aggregate metrics are available, Monte Carlo is classified as `LIMITED_MONTE_CARLO` and the decision cannot approve paper-forward candidacy.

## Checks

Monte Carlo fast:

- bootstraps existing trade R/profit values
- reports probability of positive profit, 5th/95th percentile return, drawdown and losing streak proxies

Stress fast:

- spread x1.25, x1.5, x2
- slippage x1.5, x2
- commission increase
- remove best 5% and 10%
- rollover/session exclusions

Walk-forward fast:

- splits closed trades into three temporal folds when enough data exists
- reports fold profitability and overfit warnings

Cost sensitivity:

- estimates PF/expectancy degradation under spread increases
- reports break-even spread multiplier and cost fragility score

## Decisions

- `PAPER_FORWARD_SHADOW_CANDIDATE`
- `NEEDS_MORE_ROBUSTNESS_DATA`
- `NEEDS_COST_RECALIBRATION`
- `NEEDS_STRATEGY_REWORK`
- `REJECT_BALANCED_ROBUSTNESS`

The positive decision requires at least 100 trades, positive BALANCED edge metrics, Monte Carlo positive-profit probability >= 0.60, controlled stress/cost sensitivity, and BALANCED safety flags allowing paper/shadow observation.

If the decision is `NEEDS_STRATEGY_REWORK` because walk-forward folds are negative, run Phase 24:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode walk-forward-failure-analysis --runs-root data\runs --robustness-dir data\reports\robustness --profile-runs-dir data\reports\profile_runs --output-dir data\reports\stability_repair
py -m agi_style_forex_bot_mt5.cli --mode stability-repair --runs-root data\runs --robustness-dir data\reports\robustness --profile-runs-dir data\reports\profile_runs --output-dir data\reports\stability_repair
```

The generated `BALANCED_STABLE` profile must be rerun with `--profile-config` and remains `NOT_FOR_DEMO_LIVE=true` until a new robustness rerun says otherwise. Missing or non-actionable stable configs fail closed.

## Reports

- `robustness_summary.json`
- `monte_carlo_fast.json`
- `monte_carlo_fast.csv`
- `stress_fast.json`
- `stress_fast.csv`
- `walk_forward_fast.json`
- `walk_forward_fast.csv`
- `cost_sensitivity.json`
- `cost_sensitivity.csv`
- `report.html`
