# Deflated Strategy Promotion Gate and significant KEEP

Date: 2026-10-22. Touches: strategy (the Strategy Promotion Gate in
`src/python/agi_style_forex_bot_mt5/strategy/scoring_engine.py`) and
backtesting/research reporting (the edge selectors in
`src/python/agi_style_forex_bot_mt5/edge_evaluation/` and the
`BALANCED_FILTERED` symbol and strategy filters in
`src/python/agi_style_forex_bot_mt5/edge_filtering/`). No risk, execution,
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
slices had at least one `KEEP`. Edge filtering (`BALANCED_FILTERED`) re-derived
its own `KEEP` from the selectors' reports with an even weaker rule (PF >= 1.10
and positive mean R on 30 trades), so its `symbols_keep` and `strategies_keep`
admitted zero-edge slices just as often.

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
     - at least 60 observations (`MIN_RETURN_OBSERVATIONS`): a supplied
       `return_sequence` shorter than that is unusable and invalidates the
       whole deflated block, even next to valid caller statistics, and the
       observations behind the statistics (the sequence length or
       `sharpe_observations`, whichever is smaller) must reach it. This floor
       holds in addition to observations >= MinTRL, so n >= max(60, MinTRL);
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
3. **Significant KEEP in edge filtering.** `edge_filtering/symbol_filter.py`
   and `edge_filtering/strategy_filter.py` re-derive their own `KEEP` from
   the selectors' `by_symbol.csv` and `by_strategy.csv`. Their `KEEP` now also
   needs the `holm_adjusted_p_value` the selectors wrote to be a finite value
   in [0, 0.05] (read with `significance.recorded_significance`). A missing
   column, a blank, malformed or out-of-range value, or a larger p-value
   fails closed to `WATCHLIST` with a reason; every other filter decision is
   unchanged. `filtered_profile_builder.py` decides no `KEEP` of its own: it
   lists the filters' `KEEP` rows as `symbols_keep` and `strategies_keep`, so
   it needs no change; with fewer `KEEP` rows it can only reach
   `REJECT_BALANCED_PROFILE` or `NO_ACTIONABLE_FILTER` more often.

### Why 60 observations

PSR, MinTRL and the Newey-West t are asymptotic. With a handful of
observations a zero-edge sequence passes them by luck: `(1.0, 1.1, 1.2)` with
every other item passing was approved (PSR(0) 0.99995, MinTRL 1.36, Newey-West
t 23.3). Zero-edge pass rates of the statistical block with one trial (every
other check passing), from simulations of 4,000-20,000 draws per cell:

| Returns | Newey-West t threshold | n = 3 | 5 | 14 | 30 | 40 | 50 | 60 | 100 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| i.i.d. normal | 2.0 (pre-registered) | 8.8% | 6.0% | 3.5% | 3.4% | 3.3% | 3.1% | 3.1% | 2.9% |
| i.i.d. Student t (3 df) | 2.0 (pre-registered) | 8.3% | 6.2% | 4.4% | 4.0% | 3.4% | 2.9% | 2.9% | 2.6% |
| AR(1), coefficient 0.3 | 2.0 (pre-registered) | 12.9% | 11.9% | 7.8% | 6.2% | 5.5% | 4.9% | 4.8% | 4.0% |
| AR(1), coefficient 0.3 | 3.0 | 11.3% | 8.9% | 2.9% | 1.5% | 1.1% | 0.9% | 0.8% | 0.8% |

Positively autocorrelated per-day returns at the pre-registered threshold are
the binding case: they stay above 5% through 40 observations, because the
Newey-West lag rule corrects too little in short samples, and first drop
below 5% near 50. At 60 every simulated case is below 5% with some margin, so
the floor is 60. That also rules out a per-day sequence covering only the
14-day forward window: a per-day sequence needs at least 60 days, and a
per-trade sequence at least 60 trades.

## Validation

`tests/python/test_deflated_promotion_gate.py`,
`tests/python/test_edge_selector_significance.py` and
`tests/python/test_edge_filter_significance.py`, with fixed seeds:

- Best of 20 or 50 zero-edge strategies (300-400 trades each), every other
  item of the evidence passing and PBO favourable (0.0) or computed by CSCV:
  0 of 200 universes approved with trial Sharpes supplied, at most 2 of 200
  with only the trial count. The old checks approve all of them.
- One pre-registered zero-edge strategy with the relaxed t threshold: 10 of
  400 approved (2.5%).
- Zero-edge sequences of exactly 60 observations, one trial: 14, 13 and 11 of
  400 approved (3.5%, 3.3%, 2.8%) for normal, Student t (3 df) and
  fixed-target returns at the pre-registered threshold, and 2 of 400 (0.5%)
  for AR(1) returns at t >= 3.0. Every sequence of 3, 5, 14, 30 or 59
  observations is rejected.
- Boundary cases just below each threshold (PSR(0) 0.949, deflated Sharpe
  0.949, MinTRL one observation above n, 59 observations, Newey-West t 2.999
  and 1.999), a computed PSR(0) of about 0.90 with MinTRL taken at 95%
  confidence, a computed deflated Sharpe of about 0.89, and every kind of
  unusable sequence or trial-Sharpe list next to otherwise passing caller
  statistics are all rejected.
- A planted edge (500 trades, mean 0.35 R, one trial, complete forward
  evidence): approved for 100 of 100 seeds.
- Edge selectors on 200 universes of 20 zero-edge slices: universes with any
  `KEEP` fall from 100% to 2%, and kept slices from 36.6% to 0.1%. A planted
  0.4 R strategy with 200 trades among 19 zero-edge slices stays `KEEP`. A
  Holm-adjusted p of about 0.069 (one-sided p 0.0345 in a family of two) is
  `WATCHLIST`, so the selectors' level is 0.05, not 0.10.
- Edge filtering on 200 universes of 20 zero-edge slices passed through the
  selectors and a CSV round trip: universes with any filter `KEEP` fall from
  100% to 4.5%, and kept slices from 36.2% to 0.2%. End to end, a clearly
  significant symbol and strategy stay in `symbols_keep` and
  `strategies_keep`, and a PF 1.2, mean 0.1 R slice of 40 trades does not.
- Mutation check on a scratch copy: 25 mutants, all killed, including every
  loosened threshold (PSR 0.75, MinTRL confidence 0.80, DSR 0.80, Newey-West
  2.9 and 1.9, PBO 0.11, floor 59 or 30, selector and filter alpha 0.10),
  each dropped validity condition, the negative-drawdown, `optimization_used=0`
  and integer-flag cases, and bypassing significance in either filter.

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
- A return sequence of fewer than 60 observations, or caller statistics on
  fewer than 60, no longer pass demo mode.
- Edge filtering reads `holm_adjusted_p_value` from the edge reports. Reports
  written before the selectors produced that column, or hand-made CSVs
  without it, no longer yield filter `KEEP` rows (`WATCHLIST` instead); rerun
  `edge-evaluation` to regenerate them. The fixtures in
  `tests/python/test_phase21_edge_filtering.py` now carry the column, as the
  selectors write it, for that reason only.

## Limits

- The gate trusts caller-supplied statistics only to make a decision stricter
  than a supplied sequence would; without a sequence it trusts them as given.
  `trial_sharpes` must be on the same frequency as `return_sequence` and
  include every configuration tried (the selected one too); the trial count
  likewise includes the selected configuration and must come from the trial
  registry, not memory. An undercount by one with two configurations would
  declare one trial, setting the benchmark to zero and making the
  pre-registered t >= 2.0 reachable; the gate cannot detect it.
- The gate does not compare the length of `return_sequence` with
  `historical_trades` or `forward_paper_trades`: a per-day sequence is
  legitimately shorter than the trade count. Only the 60-observation floor
  and MinTRL apply to it.
- With a single trial CSCV is undefined; the caller must still state `pbo`
  explicitly (0.0 is the only coherent value when nothing was selected) and
  the registry must show that only one configuration was ever evaluated.
- PSR and MinTRL at PSR(0) >= 0.95 coincide up to rounding; both are kept
  because the caller can supply them separately.
- Edge filtering trusts the adjusted p-value recorded in the edge reports; it
  does not recompute it. The Holm family is the set of rows of the selector
  call that wrote the CSV. Filter output stays research-only and cannot
  enable execution.
