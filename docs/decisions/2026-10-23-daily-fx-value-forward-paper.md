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
   trading costs, and the study engine unchanged (its sha is bound). A test
   checks the book against the frozen v2 `plan.json`.
2. **Forward days.** Only days from 2026-10-26 count, after this plan was
   frozen. Earlier days only build the book's state.
3. **Prices.** The operator's MT5 `D1` exports of the nine USD pairs
   (`--mode export-history`), read from 2018-01-02.
   - The last bar of every file is dropped, because it may still be forming.
   - The rebalance calendar is anchored on the first complete signal after
     2018-01-02, so it does not move as the export grows.
4. **Inflation.**
   - The pinned World Bank file (datasets/cpi 3750e450) covers years up to
     2024.
   - Each later year comes from a World Bank API download made on the
     operator's machine (`forward_runner fetch-inflation`, the only network
     call; standard library only). It is taken the first time all ten series
     have it, fixed in the ledger and never revised afterwards.
   - Year Y is used from 1 July of Y+1. A rebalance whose inflation is still
     missing stops the record just before it; nothing is guessed.
5. **Ledger.** A hash-chained ledger on the operator's machine holds
   checkpoints. Each one records:
   - the digest of the forward returns up to its last day;
   - the rebalance decisions (directions and weights);
   - the inflation years it fixed;
   - the swap snapshots it used;
   - the statistics and the rule status.

   A later run must recompute the same past exactly. Otherwise it refuses
   (`FORWARD_HISTORY_CHANGED`) and appends nothing, so a broker that revises
   its history cannot silently change the record. It also refuses:
   - a changed engine or plan file;
   - another inflation base;
   - a ledger of another plan;
   - too short a history.
6. **Two return series.**
   - **Primary.** The study's definition (spot, study costs, 75 bps/yr mark-up
     on gross exposure). It drives the rule.
   - **Broker swap.** The mark-up is replaced by the broker's captured swap
     terms (`capture-swap-snapshot`, converted by `annualised_swap_carry`). A
     snapshot applies only to days that begin after its capture and for at
     most 35 days. A day is covered only if every held currency has captured
     terms.
7. **Decision rule (group sequential).** There is one look at each
   anniversary of 2026-10-26, at most ten. The boundaries are O'Brien-Fleming
   for one-sided alpha 0.05, c = 1.801, simulated: 5.695, 4.027, 3.288,
   2.848, 2.547, 2.325, 2.153, 2.014, 1.898, 1.801.

   | Status | Condition |
   |---|---|
   | CONFIRMED | At a look, the Newey-West t of the primary daily returns reaches that look's boundary, and the broker-swap series covers at least 80% of the days with a positive total. |
   | ABANDONED_FUTILITY | From the second look, the t is at or below -1. |
   | ABANDONED_DRAWDOWN | At any time, the primary drawdown reaches 12%. |
   | ENDED_WITHOUT_CONFIRMATION | Ten looks pass without a confirmation. |
   | ONGOING | Between looks. Statistics are shown but decide nothing. |

## Rejected alternatives

- **Re-scoring the 2017-2026 holdout.** Forbidden by v2's kill rule, and it
  is exactly the selection the protocol exists to stop.
- **A fixed-horizon test.** A single test at year 5 or 10 has no early stop
  for a losing book and no earlier confirmation for a strong one.
- **FRED noon rates.** They are not tradable prices, and the forward record
  should be the operator's own execution venue.
- **Starting flat at the forward start.** It would add an arbitrary entry
  date. The continuous book is deterministic from 2018-01-02.

## Consequences

- **Power, stated before any forward day.** Simulated with the rule above:

  | True net Sharpe | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.8 |
  |---|---|---|---|---|---|---|
  | P(CONFIRMED within 3 years) | 0.00 | 0.00 | 0.00 | 0.01 | 0.01 | 0.03 |
  | P(CONFIRMED within 5 years) | 0.02 | 0.03 | 0.05 | 0.08 | 0.12 | 0.23 |
  | P(CONFIRMED within 10 years) | 0.15 | 0.23 | 0.33 | 0.45 | 0.57 | 0.79 |

  At a true net Sharpe of 0, P(CONFIRMED within 10 years) is 0.05.

  For the edge that v2 measured (about 0.4 before any decay), confirmation
  within a few years is very unlikely. The tracking mainly protects money:
  it abandons a losing book early and never confirms a lucky one.
- **What the operator must do.** The operator runs it, at least once per
  rebalance (about every four weeks):
  - export D1 bars;
  - capture a swap snapshot;
  - run the tracker.

  After each July, the operator also downloads the new inflation year. The
  ledger, the exports and the snapshots stay on the operator's machine and
  must be backed up.
- **Late runs.** The rule is deterministic, so a late run cannot choose
  anything. Lateness is recorded on each decision.
- **Integrity limit.** The hash chain proves the record was not edited, not
  that the broker data are authentic. The operator's exports are trusted.
- **Live trading stays out of scope.** A CONFIRMED status only allows opening
  a decision record about it, and AGENTS.md's requirements still apply in
  full: `LIVE_TRADING_APPROVED`, an account whitelist and an approved ADR.
- **Compatibility.**
  - The study engine (`ENGINE_FILES`) is unchanged, so v1 and v2 still
    reproduce as documented.
  - New modules and one plan builder are added.
  - The forward plan binds the sha of the study engine, `forward.py` and
    `broker_swap_snapshot.py`. A future change to any of them needs a new
    forward plan.
