# Include the capital baseline in realized-trade metrics

Status: accepted for research reports; no execution or promotion authority.
Scope: backtesting and observability. Engine version: 0.3.1.

Review of diagnostic 9aba352 found that resampled returns dropped the first
period and recovery factor used percentage drawdown times initial capital.
Curves without auxiliary candles could also begin after the first realized
loss and omit its drawdown.

Keep initial capital as an explicit first observation, followed by the net
realization at the same timestamp when necessary. Keep every close timestamp
alongside optional candle times. Use the actual maximum monetary peak-to-trough
decline for recovery and include the first calendar period against capital.

Public signatures and curve columns remain; consumers must preserve stable
ordering of equal timestamps instead of assuming uniqueness. Reporting changes
do not alter signals, fills or PnL. Historical reports remain immutable and
require recomputation before they describe this version. Realized-trade metrics
remain distinct from open-position mark-to-market and unknown intrabar paths.

Verification and detailed conventions: `docs/testing/metrics-period-baseline.md`
and `tests/python/test_metrics_period_baseline.py`.
