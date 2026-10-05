# Explicit sequence risk and post-trade evidence

Status: accepted for research and paper diagnostics. Scope: backtesting only.

## Reproduced defects

The realized-metric engine correctly sorts historical trades by close time.
Passing permuted historical records to that engine undid Monte Carlo shuffles.
Appending copies of a historical losing trade also inserted those copies at its
old close time, instead of appending losses to the synthetic sequence. A session
stress only changed a metadata label; the claimed one-bar delay was a fixed 5%
profit haircut. Neither operation evaluated execution or market timing.

## Decision

`shuffled_metrics` and appended loss streaks use `SequenceMetrics`, calculated
directly over an integer trade index including initial capital at index zero.
No synthetic market timestamps are created. The sequence, source indices and
equity path are inspectable; appended hypothetical outcomes have null source
indices. Source trades retain their original timestamps and are never mutated.

Monte Carlo samples fixed currency PnL using seeded NumPy PCG64, either IID
bootstrap or permutation. It does not resize positions, compound exposure,
simulate fills or preserve market dependence under IID bootstrap. `risk_of_ruin_pct`
is retained for compatibility, but its event is explicitly
`MAX_PEAK_DRAWDOWN_AT_LEAST_THRESHOLD`, measured in percent. A 30% peak drawdown
is not insolvency. No insolvency probability is claimed. The negative fifth
percentile of maximum drawdown remains the severe 95% tail field for compatibility.

Balance must be finite and positive; seed and iteration count must be integers
(seed >=0, iterations >0); threshold must satisfy 0 < threshold <=100. Boolean,
non-numeric, non-finite and overflowing values fail before a valid report can be
produced. Thresholds and legacy classification cutoffs are unchanged.

Cost and concentration perturbations are `POST_TRADE_APPROXIMATION`. Extra spread
is charged once, extra slippage on both sides, and input commission is assumed
round trip. Tick value, lot and instrument conversion remain fixed. These are
monetary penalties against supplied PnL, not changed fills or rerun risk gates.
R uses the original PnL/R risk denominator when available, otherwise initial SL
distance and supplied tick conversion. Every actual penalty recomputes R using
that unchanged denominator. Removing a best trade removes an occurrence, not all
references to the same Python object. Tied records retain stable source order.

Periodic trade omission and fixed profit haircut are named for their actual
transformations. Entry delay, session shift, fill rate and missing bars each have
`NOT_MODELED`, null metrics and `REQUIRES_EXPLICIT_QUOTE_REPLAY`. Empty sources are
`NO_INPUT`. Artificial losses use the worst observed negative PnL or the negative
smallest nonzero positive PnL; an all-zero sample is `INSUFFICIENT_INPUT`, without
inventing a loss amount. Only `COMPLETED` scenarios enter completed counts or
legacy diagnostic scoring. None of these statuses authorizes promotion.

## Reproducibility and compatibility

Public input signatures remain unchanged. `shuffled_metrics` now returns
`SequenceMetrics` rather than `BacktestMetrics`; consumed economic attributes
retain their names. Calendar, Sharpe/Sortino, duration, exposure and excursion
attributes are null or empty mappings, because they are unavailable on a synthetic
axis. Missing source R is null, not fabricated zero. `StressResult` adds status
and evidence scope, and its metrics may be null. Callers must check status before
reading metrics. Stress scenario names/counts change to stop claiming unsupported
checks; the legacy summary classification remains an observational diagnostic.

Report evidence version 2.0 includes exact consumed inputs, effective settings,
runtime versions, dataset/configuration hashes, commit and source-tree hash via
`RunManifest`. `inputs.json` can reproduce the numeric calculation. Stress also
exports `scenarios.json` with full metrics and synthetic paths. The fixed manifest
reference time is an identity anchor, explicitly not an event timestamp. Runtime
versions participate in configuration identity. Reports do not authenticate an
upstream strategy or broker: absent upstream provenance remains `UNKNOWN`.
Cost basis for Monte Carlo is exactly the supplied PnL, with no recalculation.
When callers provide both selected trades and a CSV reference, selected trades
remain authoritative and the file hash is recorded separately without claiming
that file and selected sequence are equal. Arbitrary trade metadata is not copied
to stress evidence because these calculations do not consume it.

Existing evidence remains historical. Use new output directories for corrected
reports; do not reinterpret pre-2.0 outputs as proof of the corrected checks.
All output has `promotion_eligible=false`, `operational_scenarios_tested=false`,
and sealed paper-only execution flags. Quote replay with provenance and explicit
scenario transformations is required before asserting operational stress results.

## Research consumer compatibility

`research_runner` consumes only `COMPLETED` results with finite net PnL and the
declared post-trade scope. It records all other statuses, counts and null metrics
in each candidate's validation artifacts. Unsupported scenarios leave evidence
incomplete; malformed results or no completed evidence cannot be classified as
passed. Negative completed results retain the former rejection rule. Report
totals distinguish completed, unsupported, no-input, insufficient and invalid
scenarios, with explicit observational and no-promotion flags.

The existing research loop currently reuses one observed outcome as train and
test and does not pass generated candidate parameters to its backtest callback.
This compatibility fix does not implement parameter application or independent
testing. It declares `OOS_NOT_EVALUATED` and `candidate_parameter_application=false`
in the summary and registry, and caps favorable assessment recommendations at
`WATCHLIST`. The generated mix therefore contains no approved strategies from
this runner. These limitations must be fixed and separately validated before
parameter comparison or out-of-sample evidence can be claimed.

## Verification

`tests/python/test_monte_carlo_stress_evidence.py` uses independent cash-flow and
cost oracles, malformed inputs, deterministic artifact reproduction and explicit
unmodeled scenarios. Before implementation, 40 of its first 43 tests failed.
No strategy thresholds, fills, broker connections or execution paths were changed.
