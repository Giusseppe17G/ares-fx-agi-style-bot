# Realized-trade metric baseline correction

Engine/report version: `0.3.1`. Scope: backtesting metrics only. Trade signals, simulated fills, costs, stops,
parameters and sizing are unchanged. Public function signatures and the
`timestamp`/`equity` curve columns remain compatible.

`build_equity_curve` now starts with the supplied initial capital. If the first
observed timestamp contains a close, two ordered rows share that timestamp:
capital before the realization, then capital after its net PnL. This avoids
inventing an earlier quote or losing the first result. Simultaneous closes are
summed once; their unknown intra-timestamp ordering does not invent extra equity
peaks. Optional candles add observations, but every actual close timestamp is
also retained so a peak or loss between candle times cannot disappear.

`calculate_metrics` sorts trades by UTC close time, then entry time and identity.
It normalizes a supplied curve chronologically using a stable sort and restores
a missing initial-capital observation. First-period day/week/month returns use
initial capital as their denominator; later periods use the previous observed
period close. Weeks retain the existing Sunday-ending convention. Daily
drawdown includes the previous day's closing realized equity before the first
current-day result. Monthly trade grouping uses UTC consistently.

Recovery factor is net realized profit divided by the maximum observed monetary
peak-to-trough decline. For equity `100 -> 80 -> 200 -> 170`, max drawdown is
20%, maximum monetary drawdown is 30, net profit is 70, and recovery is `70/30`.
Multiplying the 20% drawdown by initial capital would incorrectly use 20.

Limitations: this is realized closed-trade accounting, without open-position
mark-to-market or unobserved intrabar paths. Candle density can affect sampled
drawdown percentiles. Worst-period reports reflect periods represented by the
curve; monthly trade summaries list months containing closed trades. Sharpe
and Sortino retain the existing trade-return formulas and scaling; this change
does not establish calendar annualization or statistical comparability across
different trading frequencies. Loss streaks use the documented chronological
trade order, while equity combines simultaneous realizations.

Historical diagnostic artifacts, including run `9aba352`, remain unchanged and
do not certify the corrected metrics. Recompute diagnostics into a new output
directory with source/config/data identifiers before interpreting new reports.

Verification: `tests/python/test_metrics_period_baseline.py` covers a lone first
loss, first calendar periods, growing peaks, monetary/percentage drawdown
differences, simultaneous closes, candle alignment, chronological invariance,
UTC month boundaries and externally supplied curves missing the baseline.
