# Tick value from the broker or from price, never an assumed 1.0

Date: 2026-10-17. Touches: risk/backtesting/observability (monetary units of
assumed instrument metadata and paper PnL audits). No strategy, execution,
Expert or MQL5 behaviour changes. Execution stays removed and `DEMO_ONLY`
unchanged.

## Context

`assumed_fx_spec` gave every placeholder instrument `tick_value=1.0`. That is
right for a USD-quoted pair with a 0.00001 tick and a 100,000 contract, and
wrong for everything else: one 0.001 JPY tick on 100,000 USD is 100 JPY, about
0.67 USD near 150, so every USDJPY profit, loss and drawdown in a backtest on
assumed metadata was about 1.5 times too large. Crosses (EURJPY, EURGBP) got the
same constant with no conversion at all. The paper PnL engine and the paper
PnL audit fell back to the same 1.0 when a trade carried no tick value. With
`allow_assumed_instruments=False`, a symbol missing from a dataset sidecar was
still priced with the placeholder.

## Decision

- `derive_tick_value` in
  `src/python/agi_style_forex_bot_mt5/core/instruments/registry.py` is the only
  way to compute a USD tick value without a broker: `tick_size * contract_size`
  when the quote currency is USD, `tick_size * contract_size / price` when the
  base currency is USD, using the pair's own price. Anything else, and a
  USD-base pair without a finite positive price, raises `InstrumentError`.
  MT5 `trade_tick_value` still wins wherever it exists.
- `assumed_fx_spec(symbol, reference_price=...)` derives its tick value this
  way. `assumed_fx_point` serves callers that only need the price grid.
- Backtests on assumed metadata price a USD-base pair at the first close of
  their data (`assumed_instrument_for_bars`): the value a `symbol_info` snapshot
  would report at the start of the run, with no look-ahead. The per-bar
  snapshot fallback uses that bar's close. Strict runs now refuse a symbol that
  the sidecar lacks, and a run that assumed any symbol says so in
  `instrument_metadata_assumed`.
- Paper PnL without a reported tick value is derived from the exit (or current)
  price; a reported but unusable value raises. The lifecycle audit reports such
  a trade as `PNL_TICK_VALUE_UNAVAILABLE`, and the formula audit flags
  `TICK_VALUE_UNAVAILABLE` instead of comparing against 1.0. The paper PnL audit
  status checks that flag before every status that can lead to a new clearance
  (drawdown history leak, scaling fixed or partially fixed): such an audit is
  `PAPER_PNL_AUDIT_INCONCLUSIVE` and `KEEP_BLOCKED`, unless another trade shows
  a proven formula bug, which is still reported as that bug (also blocked).
- Signal-frequency calibration records a cross once as
  `INSTRUMENT_METADATA_UNAVAILABLE` (required data missing) instead of counting
  its signals. Counting signals does not use the tick value, but its snapshots
  no longer carry an invented one, so cross calibration waits for broker
  metadata. USD-quoted and USD-base pairs are counted as before.
- The synthetic parity fixture derives its tick value the same way (1.0 for its
  default EURUSD), so another symbol no longer inherits the EURUSD value.

## Effect on results

USD amounts on assumed USDJPY metadata (profit, loss, drawdown, planned risk)
are multiplied by `100 / first close`, about 2/3 near 150. R-multiples are unchanged
without commission, and slightly lower with a fixed per-lot USD commission:
gross PnL and planned risk both scale by the tick value, the commission does
not. A +0.48 JPY USDJPY trade with 0.52 JPY to the stop at 150 has R 0.9231
either way without commission; with 7 USD per lot (the cost used by
`scripts/prepare_inspected_development_study.py`) it was 0.9096 and is now
0.9029. Trades and signals do not change (lots are fixed; the strategy does not
read the tick value). Without commission profit factor and win rate do not
change either; with one they can only fall, as the same fixed cost takes a
larger share of each smaller USD amount.

## Limits

The derived value is static per run: there is no dynamic conversion, so a long
USDJPY backtest still misstates trades far from the first close (by the ratio
of the two prices). Account currencies other than USD and crosses need broker
metadata. The assumed contract size of 100,000 remains an assumption, labelled
as before. `CostModel()` keeps its USD-quoted defaults for callers that pass
explicit candidates. Evidence produced before this change with assumed USDJPY
metadata overstated USD amounts and is not regenerated; the archived
trend-pullback v1 run carries a dated note saying so
(`docs/testing/evidence/2026-10-05-shared-pipeline/predeclared-3e9b4d4/2026-10-17-usdjpy-tick-value-note.md`).

Follow-up, not done here: `run_benchmarks`
(`src/python/agi_style_forex_bot_mt5/benchmarks/benchmark_runner.py`) still runs
its baselines through `Backtester` with `CostModel()` defaults (tick size
0.00001, tick value 1.0) on every symbol, while the ensemble row on the same
symbol is now valued from the assumed instrument. Ensemble-versus-baseline USD
comparisons on JPY pairs are therefore inconsistent. Aligning them is more than
one line: it changes the baselines' spread and tick geometry, and a cross needs
a skip row instead of an error.
