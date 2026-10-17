# Engine 0.4.0: bid bars, gaps and exit-bar spread

Date: 2026-10-17. Touches: backtesting only (offline Python research engine).
No strategy, risk, execution, Expert or broker changes; `DEMO_ONLY`, the
execution locks and the entry spread gate are unchanged. Contract text:
PROJECT_SPEC 7.8 and 12.3.

## Context

Up to engine 0.3.2 the backtester read OHLC bars as mid prices. A SELL stop
triggered on bar prices instead of the ask, the exit reused the entry bar's
spread, a gap through the stop filled at the stop, and the per-trade
mean/std times sqrt(n) was published as `sharpe`. MT5 history bars are bid
quotes, so stops, targets and R-multiples were priced on the wrong side and the
"Sharpe" grew with the number of trades.

## Decision

- **Bid bars.** A BUY opens on the ask (bid open plus that bar's spread) and
  its SL/TP trigger on the bid. A SELL opens on the bid and its SL/TP trigger on
  the ask, bar prices plus each bar's spread. MAE/MFE and break-even/trailing
  excursions use the same closing side.
- **Valid levels.** Besides `sl < entry < tp` against the fill, SL and TP must
  lie strictly on both sides of the quote that triggers them at entry: the bid
  for a BUY, the ask for a SELL. Otherwise the candidate is rejected with
  `BUY candidate requires sl < bid < tp at entry` or
  `SELL candidate requires tp < ask < sl at entry`, never simulated as an
  instant stop. This mirrors the broker's side for stop checks.
- **Gaps.** Exits go through the shared `GapModel`: an open beyond the stop
  fills at that worse open (`gap_through_sl`), an open beyond the target fills
  at the target, and a bar touching both is a stop.
- **Moved stops.** Break-even and trailing move the stop at a bar's close from
  that bar's extreme; it applies from the next bar. A gap is flagged only when
  the previous closing-side close was on the safe side of the applied stop. If
  that close had already crossed the moved stop, the price went through it
  inside that bar: the exit fills at the stop level, with the usual slippage,
  flagged `moved_stop_crossed_in_prior_bar`, whatever the next open.
- **Exit spread.** The exit fill uses the exit bar's spread. A missing held-bar
  spread assumes the widest spread the entry gate admits, never zero. The gate
  decides entries only; it never refuses a protective exit.
- **Statistics.** `t_stat` is the per-trade statistic. `sharpe` is annualised
  from weekday mark-to-market equity, flat days included, beside skew,
  non-excess kurtosis, CAGR and Calmar. Below 20 daily returns there is no
  Sharpe and below 261 (one year of weekdays) no CAGR or Calmar;
  `daily_metrics_flags` names the shortfall, or `MARK_TO_MARKET_UNAVAILABLE`
  when there are no usable marks (walk-forward scoped folds, raw trade lists).
  A value above the thresholds is still not evidence by itself.
- **Signal snapshots** keep the mid convention described in PROJECT_SPEC 12.3;
  they only produce SL/TP levels and features.

## Alternatives rejected

- Mid bars: misplace every SELL trigger by the spread and cannot be checked
  against MT5 bid history.
- Filling a gap at the stop: optimistic whenever the market opened beyond it.
- Flagging every open beyond a moved stop as a gap: biases break-even and
  trailing against themselves and makes the flag useless for audit.
- Moving signal snapshots to bid = close, ask = close + spread now: it changes
  candidate levels of recorded studies. It needs its own engine version.

## Consequences and verification

Reports from engines before 0.4.0 must be re-evaluated before use as evidence,
without overwriting them. Round-trip spread cost per trade is unchanged;
trigger levels, exit fills and R-multiples change. Signal levels still sit half
a spread below what a forward run would build on the same bid bar (pending).

Regressions: `tests/python/test_backtester_fills.py`, the bid/closing-side
parity case in `tests/python/test_phase82_backtest_live_parity.py` and the
scoped-fold assertion in `tests/python/test_walk_forward_temporal_isolation.py`.
Synthetic fixtures check the software, not a trading edge.
