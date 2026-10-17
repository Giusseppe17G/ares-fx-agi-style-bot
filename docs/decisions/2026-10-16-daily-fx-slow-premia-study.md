# Daily FX slow-premia study inside the bot's invariants

Date: 2026-10-16. Touches: research and backtesting only
(`src/python/agi_style_forex_bot_mt5/research/`). No strategy, risk,
execution, Expert or production Python behaviour changes. Execution stays
removed (release-lock ADR) and no verdict of this study authorises it.

## Context

The predeclared intraday study of trend-pullback v1 was negative (25 of 27
cells lost money after costs), and published evidence on intraday indicator
rules for FX majors is the weakest of all the families reviewed. The only
FX premia with long out-of-sample records after costs are slow ones: time-series
momentum over about 12 months (Moskowitz, Ooi & Pedersen 2012), carry
(Lustig, Roussanov & Verdelhan 2011; Koijen et al. 2018) and their mix
(Burnside, Eichenbaum & Rebelo 2011). Their realistic Sharpe ratios are
0.2-0.5, so a test must be able to tell such a small edge from luck and from
the number of configurations tried.

The existing `research/daily_fx` engine rebalanced freely every day, ignored
the bot's invariants, read the FRED H.10 file with the wrong quote convention
for four currencies, dated MT5 D1 bars by their open, and let the holdout be
re-scored by choosing another output path.

## Decision

1. **Engine (`daily_fx/portfolio.py`).** A day-by-day simulation of a book of
   currencies against USD:
   - target weights of decision day d use data up to d and trade at the close
     of d + 1; between rebalances the weights drift with prices;
   - every position carries a catastrophe stop (2.5 rebalance-period sigmas)
     and a take-profit (3x the stop distance), checked on daily closes; a
     stopped position stays flat until the next rebalance;
   - every rebalance applies the bot's limits from `config/defaults.example.ini`:
     0.5% risk to the stop per position, 5% open risk, 10 positions, plus a
     3% cap on the net risk of the USD leg that every position shares; on a
     day whose loss reached 3%, or while open positions are down 5%, only
     reductions are allowed, and re-entry waits for the next rebalance;
   - an incomplete target trades flat; a month without a rate ends the
     simulation instead of carrying a stale rate;
   - costs: one-way bps per currency on turnover (stop exits included), a
     swap mark-up on gross exposure, and the rate differential when the
     hypothesis earns carry; both accrue by calendar days elapsed.
2. **Data (`daily_fx/data.py`).** Every FRED H.10 series in
   github.com/datasets/exchange-rates is currency per USD and is inverted.
   A run of five identical published values is rejected as a stale feed.
   MT5 D1 bars are dated by the day on which they close. OECD monthly
   3-month rates are used from the month after their own, never older.
3. **Study (`daily_fx/study.py`).** A frozen plan binds hypotheses, variants,
   periods, costs, limits, controls, gates, the sha256 of the price and rate
   files and the sha256 of the engine sources. Development only receives data
   up to its end. Development gates (all must hold): Sharpe >= 0.3,
   Newey-West t >= 2.0, Holm-adjusted p <= 0.05 across hypotheses, deflated
   Sharpe >= 0.95 over every trial, PBO <= 0.30, Hansen SPA_c p <= 0.05,
   beating 95% of random-sign books as persistent as the hypothesis' signal
   and (for timing hypotheses) of its own signal shifted in time, positive Sharpe at doubled costs, drawdown < 12% and no currency
   above half of the gross profit. Holdout verdicts: `REJECTED` unless the
   holdout Sharpe and the Sharpe at doubled costs are positive and the
   drawdown stays below 12%; `PASSED_RESEARCH` also needs a holdout
   Newey-West t >= 2.0 and a development PBO <= 0.10; otherwise `WATCHLIST`.
4. **Trial ledger (`research/trial_registry.py`).** An append-only JSONL file
   chained by sha256, shared by every plan and committed after each phase,
   records every trial, the controls, the development summary (with a digest
   of the development result) and the holdout result. The holdout follows
   the ledger, not the development file. A second development or holdout of
   a plan is refused, and so is any plan whose dates overlap a holdout
   already scored on the same prices, or a holdout whose dates another plan
   developed on. The plan also binds the Python, numpy and pandas versions.
5. **Plan v1 (`daily_fx/plans.py`)** is frozen with
   `python -m agi_style_forex_bot_mt5.research.daily_fx.runner freeze` and
   pre-registered in `docs/research/daily-fx-slow-premia-predeclared-v1.md`
   before any of its results exist.

## Consequences

- Results describe a book the bot is allowed to run. Under its invariants the
  book's volatility is low (about 2-4% a year), so even a real premium earns
  little in absolute terms; that is a property of the invariants, not of the
  engine.
- A `PASSED_RESEARCH` or `WATCHLIST` verdict only allows designing a daily
  paper path with its own ADR. The Strategy Promotion Gate (PROJECT_SPEC 12.1)
  is unchanged and still applies in full before any executable demo.
- H.10 noon rates are not tradable prices; execution realism needs broker D1
  bars. The OECD rates end in 2020-06, so carry hypotheses can only be scored
  up to then until an operator supplies a dated, sourced rate file.
- Compatibility: additive. `PortfolioConfig` gains `shift_days`, `backtest`
  gains `limits` and `rates`, the result gains `contributions`, and the FRED
  loader's convention is corrected. No public contract of the bot changes.
