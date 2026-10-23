# Forward paper tracking of the v2 real-value book

Date: 2026-10-23. Touches: research only
(`src/python/agi_style_forex_bot_mt5/research/daily_fx/forward.py`,
`forward_runner.py`, `plans.py`). No strategy, risk, execution, Expert or
production behaviour changes. Execution stays removed (release-lock ADR), and
no outcome of this tracking authorises it.

## Context

Plan v2 (`2026-10-23-daily-fx-real-value-v2-study.md`) rejected the
five-year real-value book at its development gate. It passed 12 of 13 gates
(net Sharpe 0.39, Newey-West t 2.06) but not the programme-wide deflated
Sharpe ratio (0.77 against 0.95). Its kill rule forbids re-tuning the book or
scoring it on 2017-2026. Every new backtest of another idea raises the
deflation bar of the next one.

The only evidence that cannot have been fitted is data that did not exist
when the rule was frozen. The operator asked for the path with the highest
honest chance of ending with a bot that makes money. Tracking the frozen
book forward, on the operator's own broker data, is that path.

## Decision

1. **What is tracked.** The forward plan `value_forward_v1` (`plans.py`)
   tracks plan v2's book exactly: the same `PortfolioConfig`, invariants and
   trading costs. A test checks the book against the frozen v2 `plan.json`.
2. **Forward days.** Only days from 2026-10-26 count, after this plan was
   frozen. Earlier days only build the book's state.
3. **Prices.** The operator's MT5 `D1` exports of the nine USD pairs
   (`--mode export-history`).
   - The last bar of every file is dropped (it may be forming).
   - The panel ends on the last day that every pair has. It is never
     forward-filled past it.
   - A pair more than one business day behind refuses the run
     (`PRICES_STALE`). `export-history` skips a failing symbol and still
     exits 0, which would otherwise leave a stale file.
   - The panel starts exactly on 2018-01-02, and every pair must reach back
     to it. Holidays are filled only from earlier bars, so the rebalance
     calendar is anchored on a fixed day and does not move as the export
     grows.
4. **Inflation.**
   - The pinned World Bank file (datasets/cpi 3750e450) covers years up to
     2024.
   - Each later year comes from a World Bank API download made on the
     operator's machine (`forward_runner fetch-inflation`, the only network
     call; standard library only). It is taken the first time all ten series
     have it, fixed in the ledger and never revised.
   - Year Y is used from 1 July of Y+1. A rebalance whose inputs are missing
     stops the record on the day before it. The tracker detects this from
     the signal itself, so an incomplete decision is never sealed.
5. **Ledger.** A hash-chained ledger on the operator's machine holds
   checkpoints. Each one seals its new days:
   - primary returns;
   - broker-swap returns (null where uncovered);
   - every close of the nine currencies not yet sealed (the first checkpoint
     seals all closes from 2018-01-02);
   - the decisions;
   - the inflation years fixed;
   - the sha256 of every export, the inflation supplement and its download
     record, and the swap snapshots seen and used.

   A later run must:
   - recompute every sealed primary return within an absolute 1e-10;
   - read every sealed close within a relative 1e-12;
   - recompute every sealed decision exactly.

   A broker revision of a pair the book does not hold, or of pre-start
   history, is therefore refused too. Codex found this gap on the PR before
   the forward start. Otherwise it refuses
   (`FORWARD_HISTORY_CHANGED`) and appends nothing. The tolerance lets
   last-bit numerical noise between machines pass, never a real revision.

   Broker-swap values of sealed days come from the ledger and are never
   recomputed. A snapshot that claims to predate the last checkpoint is
   ignored unless that checkpoint saw it. A final status closes the record.
   It also refuses:
   - a changed engine or plan file;
   - another inflation base;
   - a ledger of another plan;
   - missing or too short exports.
6. **Two return series.**
   - **Primary.** The study's definition (spot, study costs, 75 bps/yr
     mark-up on gross exposure). It drives the rule.
   - **Broker swap.** The mark-up is replaced by the broker's captured swap
     terms (`capture-swap-snapshot`, converted by `annualised_swap_carry`;
     only the `POINTS` swap mode converts). A snapshot applies to days that
     begin after its capture, for at most 35 days. A day is covered only if
     every held currency has convertible terms. Unconvertible symbols are
     reported with their reason.
7. **Decision rule (group sequential).** There is one look at each
   anniversary of 2026-10-26, at most ten. The boundaries are O'Brien-Fleming
   for one-sided alpha 0.05, c = 1.801, simulated (an independent review
   found 1.7998 with 2 million paths): 5.695, 4.027, 3.288, 2.848, 2.547,
   2.325, 2.153, 2.014, 1.898, 1.801.

   | Status | Condition |
   |---|---|
   | CONFIRMED | At a look, the Newey-West t of the primary daily returns reaches that look's boundary, and the broker-swap series covers at least 80% of the days with a positive total. |
   | ABANDONED_FUTILITY | From the second look, the t is at or below -1. |
   | ABANDONED_DRAWDOWN | At any time, the primary drawdown reaches 12%. |
   | ENDED_WITHOUT_CONFIRMATION | Ten looks pass without a confirmation. |
   | ONGOING | Between looks. Statistics are shown but decide nothing. |
8. **Code binding.** The plan binds the sha256 of:
   - the study engine;
   - `forward.py`;
   - `forward_runner.py`;
   - `broker_swap_snapshot.py`;
   - `core/instruments/registry.py`.

   The operator therefore runs the tracker from a git worktree pinned at the
   freeze commit. `main` can evolve without breaking it, and a change to any
   of those files needs a new forward plan.

## Rejected alternatives

- **Re-scoring the 2017-2026 holdout.** Forbidden by v2's kill rule, and it
  is exactly the selection the protocol exists to stop.
- **A fixed-horizon test.** A single test at year 5 or 10 has no early stop
  for a losing book and no earlier confirmation for a strong one.
- **FRED noon rates.** They are not tradable prices, and the forward record
  should be the operator's own execution venue.
- **Starting flat at the forward start.** It would add an arbitrary entry
  date. The continuous book is deterministic from 2018-01-02.
- **Allowing engine updates when the past replays exactly.** A change that
  only alters future behaviour would pass unnoticed.

## Consequences

- **Power, stated before any forward day.** Simulated with the rule above.
  These are upper bounds: swap-coverage withholding is not simulated.

  | True net Sharpe | 0.0 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.8 |
  |---|---|---|---|---|---|---|---|
  | P(CONFIRMED within 3 years) | 0.00 | 0.00 | 0.00 | 0.00 | 0.01 | 0.01 | 0.03 |
  | P(CONFIRMED within 5 years) | 0.01 | 0.02 | 0.03 | 0.05 | 0.08 | 0.12 | 0.23 |
  | P(CONFIRMED within 10 years) | 0.05 | 0.15 | 0.23 | 0.33 | 0.45 | 0.57 | 0.79 |

  - A book with no edge is confirmed 5% of the time (the alpha).
  - For the edge v2 measured (about 0.4 before any decay), confirmation
    within a few years is very unlikely.
  - A losing book is not always caught early:
    - At a true Sharpe of -0.2 the rule abandons about 32% of runs within
      3 years and 57% within 10.
    - The 12% drawdown stop is nearly inert at the book's 1.6% annual
      volatility: about 2%, 8% and 21% within 10 years at Sharpe 0, -0.2
      and -0.4.
  - A real Sharpe 0.4 book is abandoned for futility about 11% of the time.
- **What the operator must do.** The operator runs it at least once per
  rebalance (about every four weeks), preferably weekly:
  - export D1 bars and check `files_created: 9`;
  - capture a swap snapshot;
  - run the tracker.

  After each July, the operator also downloads the new inflation year. A
  broker whose swap mode is not `POINTS` gives no broker-swap coverage, and
  no CONFIRMED is possible until the conversion supports it.
- **Late runs.** The rule is deterministic, so a late run cannot choose
  anything. Lateness is recorded on each decision.
- **Integrity limits.** The hash chain proves only that a ledger file was not
  edited:
  - Truncating its tail, or deleting it and starting again, is not detected
    locally. Starting again would also let a later inflation vintage be
    fixed.
  - The broker data and the inflation download are trusted.

  The operator therefore sends the ledger file at least every quarter and at
  each look, and it is committed under
  `docs/research/daily_fx_value_forward_v1/` as an external anchor. It holds
  returns, decisions, inflation figures and broker closes, and no account
  data.
- **Not done here.** The checkpoints are not yet sent as Telegram events
  (AGENTS.md expects important events there). This is pending work for the
  Telegram reviewer.
- **Live trading stays out of scope.** A CONFIRMED status only allows opening
  a decision record about it, and AGENTS.md's requirements still apply in
  full: `LIVE_TRADING_APPROVED`, an account whitelist and an approved ADR.
- **Compatibility.** The study engine (`ENGINE_FILES`) is unchanged, so v1
  and v2 still reproduce as documented. New modules and one plan builder are
  added.
