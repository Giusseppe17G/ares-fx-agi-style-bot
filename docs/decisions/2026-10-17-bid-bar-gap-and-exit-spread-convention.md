# Engine 0.4.0/0.4.1: bid bars, gaps and exit-bar spread

Date: 2026-10-17. Touches: backtesting only (offline Python research engine).
No strategy, risk, execution, Expert or broker changes; `DEMO_ONLY`, the
execution locks and the entry spread gate are unchanged. Contract text:
PROJECT_SPEC 7.8 and 12.3. Engine 0.4.1 amends only the moved-stop rule and
the daily metric flags below.

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
- **Moved stops (0.4.1, bar-close EA).** Break-even and trailing propose a new
  stop at a bar's close (break-even from entry plus lock, trailing from that
  bar's extreme), as one modification. It is accepted only when it lies
  strictly on the protective side of that bar's closing quote: below the bid
  close for a BUY, above the ask close for a SELL. The OHLC engine models no
  broker stops or freeze level (0), so the bound is the quote itself.
  Otherwise MT5 would refuse the modification as invalid stops: the previous
  stop stays whole (a refused break-even plus trailing proposal does not fall
  back to its break-even part) and the trade records
  `stop_move_flags = ("stop_move_rejected_invalid_side",)` and the count
  `stop_moves_rejected`. An accepted stop applies from the next bar. The
  stop in force is therefore always strictly on the safe side of the previous
  close, so an open beyond it is a real gap: it fills at that open, worse than
  the stop (`gap_through_sl`). No exit fills at a stop level the price did not
  trade, and an END_OF_DATA exit never reports a final stop the close had
  already crossed.
- **Exit spread.** The exit fill uses the exit bar's spread. A missing held-bar
  spread assumes the widest spread the entry gate admits, never zero. The gate
  decides entries only; it never refuses a protective exit.
- **Statistics.** `t_stat` is the per-trade statistic. `sharpe` is annualised
  from weekday mark-to-market equity, flat days included, beside skew,
  non-excess kurtosis, CAGR and Calmar. Below 20 daily returns there is no
  Sharpe, skew or kurtosis (at 20 the standard errors of skew and kurtosis are
  still about 0.5 and 1.0, so they are descriptive only) and below 261 (one
  year of weekdays) no CAGR or Calmar. Every null daily metric has a reason in
  `daily_metrics_flags`: `MARK_TO_MARKET_UNAVAILABLE` without usable marks
  (walk-forward scoped folds, raw trade lists), `INSUFFICIENT_DAILY_SAMPLE_*`
  for each threshold, `DAILY_RETURNS_ZERO_VARIANCE` or
  `DAILY_RETURNS_NOT_FINITE` (returns or their moments not representable as
  finite doubles) for Sharpe/skew/kurtosis, `CAGR_OVERFLOW` when
  growth is not a finite annual rate (CAGR and Calmar) and
  `CALMAR_ZERO_DRAWDOWN`. A value above the thresholds is still not evidence
  by itself.
- **Signal snapshots** keep the mid convention described in PROJECT_SPEC 12.3;
  they only produce SL/TP levels and features.

## Alternatives rejected

- Mid bars: misplace every SELL trigger by the spread and cannot be checked
  against MT5 bid history.
- Filling a gap at the stop: optimistic whenever the market opened beyond it.
- Flagging every open beyond a moved stop as a gap (first 0.4.0 revision): the
  stop had been placed behind the close, which MT5 refuses, so the "gap" was an
  artefact of an impossible modification.
- Filling at the stop level when the previous close had already crossed the
  moved stop (`moved_stop_crossed_in_prior_bar`, a later 0.4.0 revision):
  it assumes tick-level management. A break-even stop at entry plus lock can
  sit beyond the bar's whole traded range (trigger 0R, or lock above the
  excursion), so the trade was booked at a price that never traded; on a
  zero-drift random walk this turned a cost-only loss into a 100% win rate.
- Capping a refused stop at the close or the bar extreme: a modification the
  EA did not send. A stop trailed from the close instead of the bar extreme is
  a strategy change and needs its own version.
- Moving signal snapshots to bid = close, ask = close + spread now: it changes
  candidate levels of recorded studies. It needs its own engine version.

## Consequences and verification

Reports from engines before 0.4.0 must be re-evaluated before use as evidence,
without overwriting them; 0.4.0 reports with break-even or trailing enabled
must also be re-run on 0.4.1. Round-trip spread cost per trade is unchanged;
trigger levels, exit fills and R-multiples change. Signal levels still sit half
a spread below what a forward run would build on the same bid bar (pending).
Trailing is still measured from the bar extreme, so under bar-close validation
it only moves when the close is within the trailing distance of that extreme.
Paper trading fills a stop already behind the price at the observed quote and
does not yet refuse such moves; that parity gap is pending.

Regressions: `tests/python/test_backtester_fills.py` (including a random-walk
check that no exit fills outside its exit bar's traded range),
`tests/python/test_backtester_instrument_grid.py`, the bid/closing-side
parity case in `tests/python/test_phase82_backtest_live_parity.py` and the
scoped-fold assertion in `tests/python/test_walk_forward_temporal_isolation.py`.
Synthetic fixtures check the software, not a trading edge.
