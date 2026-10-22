# Deflated Strategy Promotion Gate and significant KEEP

Date: 2026-10-22. Touches: strategy (the Strategy Promotion Gate in
`src/python/agi_style_forex_bot_mt5/strategy/scoring_engine.py`) and
backtesting/research reporting (the edge selectors in
`src/python/agi_style_forex_bot_mt5/edge_evaluation/`). No risk, execution,
Expert or MQL5 behaviour changes. Every change only makes a decision more
conservative. Execution stays removed (release-lock ADR), `DEMO_ONLY=True` and
`LIVE_TRADING_APPROVED=False` are unchanged, and no approval below can send
anything while `EXECUTION_NOT_RELEASED` holds.

## Context

`PROJECT_SPEC.md` 12.1 recorded as technical debt that `evaluate_promotion_gate`
checked only the 12.1 OOS subset (200 trades or a justification, OOS PF > 1.15,
positive expected payoff, drawdown under the strategy limit, profit
concentration, spread/slippage sensitivity, walk-forward, some shadow signals).
It did not require the `APPROVED_FOR_SHADOW_OBSERVATION` minimums of
`docs/STRATEGY_PROMOTION_GATE.md`, nor its Phase 8 forward-shadow evidence, and
none of its checks asked whether the edge could be luck or the best of many
configurations tried. Summary statistics such as PF and expectancy are exactly
what a search over many configurations inflates.

The edge selectors (`strategy_selector.py`, `symbol_selector.py`) labelled a
row `KEEP` with PF > 1.10 and positive mean R on 30 trades. On simulated
zero-edge slices of 30-80 fixed-target trades (+1.5 R / -1 R, mean exactly 0 R)
the old rule kept 36.6% of the slices, and every one of 200 universes of 20
slices had at least one `KEEP`.

## Decision

1. **Cumulative demo gate.** `PromotionEvidence` keeps every field and default
   and gains fields that default to failing values. Demo mode now requires,
   besides the unchanged 12.1 checks:
   - (a) shadow approval: `shadow_approval_classification ==
     "APPROVED_FOR_SHADOW_OBSERVATION"`, `historical_trades >= 300` or a
     non-blank written `statistical_justification`, OOS PF > 1.25, OOS max
     drawdown in [0, 12) %, `oos_expectancy_r > 0`;
   - (b) Phase 8 forward shadow: `shadow_days >= 14` and
     `forward_paper_trades >= 200` (both, so whichever takes longer),
     `forward_profit_factor > 1.15`, `forward_expectancy_r > 0` and
     `forward_controls_passed` (an attestation of the qualitative Phase 8
     items: controlled drawdown, no severe cost or performance drift,
     compatible spread, stable storage, `order_send` never called);
   - deflated statistics, computed by the gate from an optional per-trade or
     per-day `return_sequence` with `research/edge_statistics.py`, supplied by
     the caller (`psr_zero`, `min_track_record_length` with
     `sharpe_observations`, `deflated_sharpe`, `newey_west_t`), or both, in
     which case the less favourable value of each wins:
     - PSR(0) >= 0.95 and observations >= MinTRL at 95% confidence;
     - `trials` >= 1 declared (missing or < 1 fails) and deflated Sharpe
       >= 0.95. The benchmark is the expected maximum Sharpe of
       `max(trials, len(trial_sharpes))` unskilled trials, with a Sharpe
       variance that is the larger of the null sampling variance
       `1 / (n - 1)` and the variance of the supplied `trial_sharpes`, so a
       tight or partial list of trial Sharpes can never lower the benchmark
       below the null;
     - Newey-West t of the mean >= 3.0, or >= 2.0 only when
       `single_preregistered_hypothesis is True` (a real boolean) and exactly
       one trial was tried;
     - `pbo` in [0, 0.10]; a missing PBO fails.

   Where thresholds overlap every check runs, so the strictest applies (for
   example PF > 1.25 and > 1.15, 300 and 200 trades, DD < 12% and below the
   strategy limit). Missing, malformed, non-finite or out-of-range evidence
   fails its check; mapping evidence is parsed without coercing text such as
   `"false"` into a pass, and a relaxing flag must be an explicit boolean.
   `PromotionDecision` gains `statistics` (the values used, JSON-safe), which
   the ensemble adds to its demo-mode `promotion_gate` audit payload. Shadow
   mode stays approved for audit collection exactly as before, with the same
   payload.
2. **Significant KEEP in the edge selectors.** A row that passes the old KEEP
   rule also needs a Holm-adjusted p-value <= 0.05. The p-value is the
   one-sided Student t test of H0: mean R <= 0, `t = mean_R * sqrt(n) / sd_R`
   with `n - 1` degrees of freedom, and the Holm family is every row
   evaluated in that selector call. Rows whose test cannot be computed
   (`COUNTS_ONLY`, fewer than 3 trades, missing or zero dispersion) enter the
   family with p = 1, which can only make the adjustment stricter. A row that
   passes the old rule but not this one becomes `WATCHLIST` with a reason that
   names the adjusted p-value and the family size. `edge_metrics.py` now
   reports `r_multiple_std` (sample standard deviation of the same R values
   it averages) so the test has its dispersion; the selector outputs carry
   `mean_r_t_stat`, `mean_r_p_value`, `holm_adjusted_p_value`,
   `holm_family_size` and `significance_status`. `COUNTS_ONLY` handling is
   unchanged. The Student t tail is computed with the regularized incomplete
   beta function in `edge_evaluation/significance.py` (standard library only;
   no new dependency).

## Validation

`tests/python/test_deflated_promotion_gate.py` and
`tests/python/test_edge_selector_significance.py`, with fixed seeds:

- Best of 20 or 50 zero-edge strategies (300-400 trades each), every other
  item of the evidence passing and PBO favourable (0.0) or computed by CSCV:
  0 of 200 universes approved with trial Sharpes supplied, at most 2 of 200
  with only the trial count. The old checks approve all of them.
- One pre-registered zero-edge strategy with the relaxed t threshold: 10 of
  400 approved (2.5%).
- A planted edge (500 trades, mean 0.35 R, one trial, complete forward
  evidence): approved for 100 of 100 seeds.
- Edge selectors on 200 universes of 20 zero-edge slices: universes with any
  `KEEP` fall from 100% to 2%, and kept slices from 36.6% to 0.1%. A planted
  0.4 R strategy with 200 trades among 19 zero-edge slices stays `KEEP`.

## Compatibility

- Callers that do not pass the new evidence get demo `REJECTED` (effective
  mode shadow), the fail-closed direction. No production caller requests demo
  mode; nothing can execute anyway while `EXECUTION_NOT_RELEASED` holds.
- Existing evidence that only met the old subset (for example 260 trades at
  OOS PF 1.25) no longer passes; `tests/python/test_strategy_engine.py` was
  updated for that reason only.
- Selector outputs gain columns and lose `KEEP` rows that are not significant.
  Input rows without `r_multiple_std` can no longer be `KEEP`;
  `tests/python/test_phase20_edge_evaluation.py` now gives its `KEEP` row a
  dispersion for that reason only.

## Limits

- The gate trusts caller-supplied statistics only to make a decision stricter
  than a supplied sequence would; without a sequence it trusts them as given.
  `trial_sharpes` must be on the same frequency as `return_sequence` and
  include every configuration tried (the selected one too); the trial count
  must come from the trial registry, not memory.
- With a single trial CSCV is undefined; the caller must still state `pbo`
  explicitly (0.0 is the only coherent value when nothing was selected) and
  the registry must show that only one configuration was ever evaluated.
- PSR and MinTRL at PSR(0) >= 0.95 coincide up to rounding; both are kept
  because the caller can supply them separately.
- `edge_filtering/symbol_filter.py` and `edge_filtering/strategy_filter.py`
  re-derive their own `KEEP` from `by_symbol.csv` and `by_strategy.csv` with
  the old PF/expectancy rule; aligning them with this significance test is a
  follow-up, not done here. Their output is research-only and cannot enable
  execution.
