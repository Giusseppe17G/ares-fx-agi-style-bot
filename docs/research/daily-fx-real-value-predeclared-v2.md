# Pre-registration: daily FX real value v2

Status: FROZEN on 2026-10-23 with the engine of commit 306b984, before any
result of this plan existed. Research only; no verdict of this study
authorises execution (release-lock ADR). Decision record:
`docs/decisions/2026-10-23-daily-fx-real-value-v2-study.md`.

- Plan: `real_value_v2` in `src/python/agi_style_forex_bot_mt5/research/daily_fx/plans.py`.
- Frozen plan file: `docs/research/daily_fx_real_value_v2/plan.json` (written by `runner freeze`).
- Plan hash (sha256 of the canonical plan JSON): `e8831946d99e7a058b987a5b24707c1f0e98d22c1dd8ba961aecae77437b7556`.
- Engine hash (sha256 of the engine sources): `c46e71202818a33c9f290c2d883853a475f482da4cdddb9f10823f0a5bf54270`.
- Environment: Python 3.14.4, numpy 2.4.4, pandas 3.0.2.

Any change to the code, data, parameters or gates gives a different hash, and
the runner refuses it.

## Departure from v1's reuse rule (declared)

v1's pre-registration said that any follow-up would be "a new plan scored on
data no plan has seen (in practice: forward paper data)". v2 departs from that
wording for its development phase:

- **Development reuses v1's years.** The development window includes v1's
  development years 1999-2016. v1's results for trend and carry on those years
  are known; value was never computed there.
- **Unseen data.** The verdict comes only from the holdout, 2017-01-01 to
  2026-06-30, which no plan has scored. The first development subperiod,
  1985-1998, has never been used by any plan, and it must keep a positive
  Sharpe ratio on its own.
- **v1's trials count.** The deflated Sharpe ratio counts v1's seven trials.
- **Why not stricter.** Restricting development to 1985-1998 (13.75 years)
  would need a net Sharpe ratio of about 0.85 to reach the deflated gate. No
  published currency premium comes close to that.

## Question

Inside the bot's own risk invariants, after realistic costs and counting
every development trial in the shared daily-FX ledger, do the G10 currencies that are cheap
in real terms over about five years outperform the expensive ones by enough
to survive a deflated Sharpe ratio, permuted and time-shifted controls, a
cost stress, a subperiod check and an untouched holdout?

## Data

| Input | Source | Pin | sha256 |
|---|---|---|---|
| Daily prices | FRED H.10 noon New York rates, github.com/datasets/exchange-rates `data/daily.csv` (the file v1 used) | commit c023dd8b8f87 | `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa` |
| Annual CPI inflation | World Bank FP.CPI.TOTL.ZG, github.com/datasets/cpi `data/cpi.csv` | commit 3750e450 (2025-07-01) | `182baa44c536079bea07bb8700c37c85441c3d7d5f8e6dd68fb92fcb4a7815e8` |

- **Prices.** Every H.10 series is units of currency per USD and is
  inverted. Prices are read from 1979-01-02: the 1970s pegs (runs of
  identical published values, the last one ending on 1974-11-18) are never
  read. The stale-feed and gap checks apply to every row used.
- **CPI.** The `CPI` column of the World Bank file is annual % inflation,
  not an index (the README is wrong). The loader refuses the file unless it
  matches:

  | Series and year | Value (%) |
  |---|---|
  | US 1974 | 11.05 |
  | US 1980 | 13.55 |
  | US 2009 | -0.36 |
  | US 2022 | 8.00 |
  | Japan 1974 | 23.22 |

  The tolerance is 0.1 percentage point. This rejects a CPI-index vintage and
  the GDP-deflator file (US 1974 = 9.00).
- **Inflation publication rule.** Inflation of year Y is used only from
  1 July of Y+1. The inflation window therefore ends 0.5-1.5 years before the
  price window. Asness, Moskowitz & Pedersen use the same period for both;
  this lag is declared here, not tuned. The last year in the file is 2024, so the signal is
  complete up to 2026-06-30. After that the book trades flat at the next
  rebalance.
- **Storage.** The data stay outside the repository (gitignored
  `data/historical/`: `fred/daily.csv` and `worldbank/cpi.csv`).
- **Caveats:**
  - Noon rates are not tradable prices.
  - Before 1989 the World Bank's UK series is RPI-type.
  - Values were revised by up to 1.1 pp in a single year between vintages.

## Universe and periods

- **Currencies vs USD:** AUD, CAD, CHF, DKK, GBP, JPY, NOK, NZD, SEK. USD is
  the tenth ranked currency. DKK stands for the DEM/EUR bloc because EUR
  prices start in 1999.
- **Warm-up only:** 1979-01-02 to 1985-03-31. These rows are never scored;
  the first complete signal comes about 5.5 years after the first price.
- **Development:** 1985-04-01 to 2016-12-31 (31.75 years), after the NZD
  float of 1985-03-04. Development never receives a later price or an
  inflation figure published after 2016-12-31.
- **Development subperiods:** 1985-04-01 to 1998-12-31 and 1999-01-01 to
  2016-12-31. Each must keep a net Sharpe ratio above zero.
- **Holdout:** 2017-01-01 to 2026-06-30 (9.5 years).
  - It is scored once, only if the hypothesis passes every development gate.
  - No plan has scored these dates.
  - v1 declared them as its holdout but never scored them, and the shared
    ledger holds no holdout record.

## Hypothesis (one trial, no variants)

`H1_XS_REAL_VALUE_5Y`: currency value (Asness, Moskowitz & Pedersen,
*Journal of Finance* 2013; Menkhoff, Sarno, Schmeling & Schrimpf, *Review of
Financial Studies* 2017).

**Score of each currency on decision day d** (minus its real appreciation vs
USD), the sum of two terms with the sign reversed:

- the log price on d minus the mean log price over the 261 rows that end
  4.5 years earlier (rows d-1435 to d-1175);
- the sum, over the last five published years, of ln(1 + its CPI
  inflation / 100) minus ln(1 + US CPI inflation / 100).

**Ranking and sizing:**

- USD has a score of zero.
- The nine currencies and USD are ranked. The three highest scores (cheapest)
  are long and the three lowest (dearest) short against USD.
- If USD is in a group, its leg is implied by the others, so net USD risk is
  at most one position (0.5%).
- Ties go to the ISO code first in alphabetical order.
- Every position is sized to exactly 0.5% of equity to its stop (equal
  risk), so the book holds 5 or 6 positions and 2.5-3.0% open risk.
- The only exception is the gross-leverage cap of 3, which a very-low-volatility
  currency could hit. That cannot happen in this universe.

**Timing:**

- Rebalance every 21 rows from the first complete signal.
- Decision on d, execution at the close of d+1.
- Ex-ante volatility is an EWMA with span 60.

**Returns:**

- Spot only: the rate differential the positions would earn or pay is not
  credited.
- No rate file covers 2017-2026 for all ten currencies, so any verdict is
  labelled spot-only.

## Risk invariants (the bot's limits, unchanged from v1)

- 0.5% risk to the stop per position; 5% open risk; 3% net risk on the
  shared USD leg; at most 10 positions.
- Catastrophe stop at 2.5 rebalance-period sigmas and take-profit at 3x the
  stop distance, both checked on daily closes.
- On a day whose loss (net of that day's costs) reached 3%, or while open
  positions are down 5% from the exposure taken at entry, only reductions are
  allowed. Re-entry waits for the next rebalance.
- Positions are resized at every rebalance, where entry, stop and
  take-profit re-anchor.

## Costs

- One-way bps of notional (v1's table, with DKK added):

  | Currency | bps |
  |---|---|
  | AUD | 1.2 |
  | CAD | 1.2 |
  | CHF | 1.5 |
  | DKK | 3.0 |
  | GBP | 1.2 |
  | JPY | 1.0 |
  | NOK | 3.0 |
  | NZD | 2.0 |
  | SEK | 3.0 |

- A swap mark-up of 75 bps a year on gross exposure, accrued by calendar
  day.
- Stress: all costs doubled.

## Controls

- **No trade:** PSR against a zero Sharpe ratio, and SPA_c against zero
  (2,000 bootstraps).
- **Permuted currencies:** 200 books that give the same ranking to a
  permutation of the ten currencies, USD included. Each permutation is
  distinct and none is the identity. The books have the same ranking dynamics
  and sizing, and about the same turnover, but hold the wrong currencies. On
  random walks this control was close to calibrated.
- **Time-shifted signal:** 200 copies of the signal circularly shifted by
  distinct offsets of at least 1,435 + 21 + 1 rows in both directions (gated:
  value claims timing).
  - **Not a calibrated 5% test.** The shifted copies are correlated with each
    other but not with the real book. On synthetic random walks the real book
    beat every copy about 7.7% of the time, against a nominal 5%, so the
    control is slightly lenient.
  - It is kept as a gate. The binding gate is the deflated Sharpe ratio.
- **Doubled costs:** a gate (see below).
- **Reported only:** the flipped signal, and the t of non-overlapping 21-row
  returns. If the 21-row t disagrees with the daily t, the write-up says so.

## Development gates (all must hold)

| Check | Threshold |
|---|---|
| Annualised net Sharpe | >= 0.3 |
| Newey-West t-statistic of the mean | >= 2.0 |
| Holm-adjusted p (1 - PSR vs 0), one hypothesis | <= 0.05 |
| Deflated Sharpe ratio over every development trial in the shared daily-FX ledger (v1's 7) plus this one (8). Variance of the trial Sharpes floored at 1/(n-1); each trial on its own window | >= 0.95 |
| PBO | not applicable: one predeclared configuration, no selection. v1's PBO conditions are dropped and compensated by the programme-wide deflation |
| Hansen SPA_c p | <= 0.05 |
| Share of permuted-currency books at least as good | <= 0.05 |
| Share of time-shifted books at least as good | <= 0.05 |
| Net Sharpe with doubled costs | > 0 |
| Maximum drawdown | < 12% |
| Largest single-currency share of gross profit | <= 50% |
| Net Sharpe in each subperiod (1985-04 to 1998-12, 1999-01 to 2016-12) | > 0 |
| Rebalances inside the window traded flat for lack of inputs | 0 |

**Variance floor convention.** In the floor 1/(n-1), n is the number of
observations of v2's own trial (about 8,300). This is the convention of
`2026-10-22-deflated-promotion-gate.md`.

- It requires an observed t of about 3.1.
- Averaging 1/(n-1) over v1's shorter trials (3,800-4,600 rows) would
  require about 3.6.
- The choice is declared here, before any result.

**Reproducing the benchmark.** The run records:

- the ledger head it started from;
- every programme trial it counted.

Reproducing the benchmark needs the shared ledger up to that head.

## Holdout verdicts

- `REJECTED` unless the holdout Sharpe ratio and the Sharpe ratio with
  doubled costs are positive and the drawdown stays below 12%.
- `REJECTED` also when a holdout rebalance is traded flat for lack of
  inputs.
- `PASSED_RESEARCH` if, in addition, the holdout Newey-West t is at least
  2.0. v1's condition "development PBO <= 0.10" is not applicable to a
  single configuration. It is dropped, and the programme-wide deflation of
  development compensates for it.
- `WATCHLIST` otherwise.
- Every verdict is **spot-only**. Before any paper design, a pass must be
  confirmed with the broker's real swaps (`--mode capture-swap-snapshot`).

## Power, written before any result

Synthetic Student-t(5) daily returns with the same statistical gates
(`edge_statistics`, v1's seven trial Sharpe ratios from the ledger, 400
draws per row).

- The controls, drawdown, currency-share and subperiod gates are not
  simulated, so these are upper bounds.
- An independent reviewer reproduced the table within Monte Carlo noise.
- A dress rehearsal of the whole study on synthetic data of the real shape
  (planted net Sharpe 0.55, t 3.0) passed every gate except the deflated
  Sharpe ratio (0.93).

| True net Sharpe | 0.0 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.8 |
|---|---|---|---|---|---|---|---|
| Development: Sharpe >= 0.3 and t >= 2 | 0.03 | 0.16 | 0.38 | 0.59 | 0.84 | 0.91 | 0.99 |
| Development: deflated Sharpe >= 0.95 (binding) | 0.00 | 0.01 | 0.06 | 0.17 | 0.36 | 0.55 | 0.88 |
| Holdout (9.5 years): t >= 2 | 0.03 | 0.10 | 0.13 | 0.19 | 0.34 | 0.43 | 0.68 |

**How large an edge is plausible:**

- The published gross Sharpe ratio of G10 currency value is about 0.3-0.6.
- The swap mark-up on a long-short book costs about 0.2-0.35 of it.
- After publication, decay of 30-60% is typical of published anomalies.

A realistic true net Sharpe is therefore 0-0.4. **The most likely outcome
is a rejection in development, even if the premium is real.** Across the
design reviews:

- P(`PASSED_RESEARCH`) is about 1-10%, about 2% in the central case;
- a book with no edge would reach `WATCHLIST` about a quarter of the time,
  if it ever got to the holdout.

## Holdout protection

These are v1's protections, unchanged:

- The shared hash-chained ledger records every trial, control, development
  summary and holdout result. It is committed after each phase.
- The holdout follows the ledger, not the development file.
- The ledger refuses:
  - a second development or holdout of this plan;
  - any plan whose dates overlap a holdout already scored;
  - a holdout whose dates another plan developed on.
- The plan also binds:
  - the inflation file's sha256;
  - the first price row;
  - the Python, numpy and pandas versions;
  - at least 7 prior development trials, so the run refuses a fresh ledger.

## Kill rule

A `REJECTED` hypothesis is not re-tuned (other lookbacks, terciles,
rebalance frequencies or universes are new plans that count as further
trials), and its holdout is never reused.

## Honest caveats

- **Knowledge contamination:**
  - The hypothesis was chosen knowing the published results. 1985-2011 is
    in sample for the papers, so passing development mostly replicates them
    under the bot's invariants; only 2017-2026 is after publication.
  - We know the broad FX moves of 2017-2025: the 2021-2024 yen slump hurt
    books long a cheap JPY, and USD rallied in 2022.
  - No parameter was tuned to any of this. All of them come from AMP 2013
    or from v1.
- **Development years that may not have been tradable:**
  - capital controls on AUD (to 1983) and NZD (to 1984-85);
  - SEK and NOK basket pegs (to 1992);
  - DKK realignments in the EMS;
  - discrete devaluations.

  The currency-share gate limits how much one of them can drive a pass.
- **Few independent bets.** Value positions rotate slowly. If the 21-row t
  disagrees with the daily t, the write-up says so.
- **Small absolute returns.** With equal-risk sizing at 0.5% per position,
  the book's volatility is about 1-2% a year (1.4% on synthetic data with 10%
  currency volatility). Even a real premium earns little in absolute terms.

## Results

Filled in after the runs, without editing anything above.

The development result was written by the runner to
`docs/research/daily_fx_real_value_v2/development.json`. Every trial,
control and summary was appended to the shared ledger
`docs/research/trial_ledger.jsonl` (14 records, chain verified), starting
from ledger head `233c67bf…` with v1's 7 trials counted.

### Development (run once on 2026-10-23, frozen plan of commit 1f2e6c4): REJECTED

Window: 1985-04-01 to 2016-12-30 (8,285 days, 31.75 years). The hypothesis
failed 1 of the 13 gates: the deflated Sharpe ratio.

| Check | H1 real value 5y | Gate | Pass |
|---|---|---|---|
| Net Sharpe | 0.39 | >= 0.3 | yes |
| Newey-West t | 2.06 | >= 2.0 | yes |
| Holm-adjusted p (one hypothesis) | 0.014 | <= 0.05 | yes |
| Deflated Sharpe ratio over 8 trials | **0.77** | >= 0.95 | **no** |
| PBO | not applicable | - | - |
| SPA_c p | 0.020 | <= 0.05 | yes |
| Share of permuted-currency books as good | 0.005 (none of 200) | <= 0.05 | yes |
| Share of time-shifted books as good | 0.045 (8 of 200) | <= 0.05 | yes (not a calibrated test) |
| Net Sharpe with doubled costs | 0.17 | > 0 | yes |
| Maximum drawdown | 6.1% | < 12% | yes |
| Largest currency share of gross profit | 30% | <= 50% | yes |
| Net Sharpe 1985-04 to 1998-12 / 1999-01 to 2016-12 | 0.39 / 0.39 | > 0 | yes |
| Rebalances traded flat for lack of inputs | 0 | 0 | yes |

Further figures:

| Figure | Value |
|---|---|
| Gross Sharpe (before costs and swap mark-up) | 0.61 (t 3.21) |
| Net annual return | 0.63% |
| Annual volatility | 1.62% |
| Total net return over 31.75 years | 22.2% |
| Positive years | 59% |
| Flipped signal Sharpe | -0.85 |
| Mean gross exposure | 0.43 of equity |
| Stops / take-profits / blocked rebalances | 47 / 2 / 0 |
| Daily skew / kurtosis | 0.17 / 6.97 |
| Reported only: t of non-overlapping 21-row returns | 1.86 |

Reading, without changing the verdict:

- **Strongest result of the programme so far, but not enough.**
  - It is the first book in the programme with a positive net Sharpe that
    is significant before deflation (t 2.06, Holm p 0.014).
  - It was positive in both subperiods with the same Sharpe ratio, including
    1985-1998, which no plan had used.
  - It beat all 200 permuted-currency books and 192 of 200 time-shifted
    copies, and survived doubled costs.
- **Why the deflated Sharpe ratio fails.**
  - Counting the 8 daily-FX trials, the luck benchmark is an annual Sharpe
    ratio of about 0.26, so the gate needs an observed t of about 3.1. The
    observed t was 2.06.
  - This is the outcome the power table predicted for a true net Sharpe
    ratio near 0.4: the gate passes about 17% of the time.
- **The 21-row t disagrees with the daily t.** The t of non-overlapping
  21-row returns is 1.86, below 2, while the daily t is 2.06. As declared,
  this is stated: it weakens the evidence further.
- **Costs.** Trading costs and the swap mark-up take about 0.22 of Sharpe
  (gross 0.61, net 0.39). The book is spot only: the carry its positions
  would earn or pay is not in these numbers.
- **Small absolute returns.** Under the invariants the book earned 0.63% a
  year at 1.6% volatility.

Reproduction check (2026-10-23):

- The development was re-run from a copy of the frozen plan, into a copy of
  the shared ledger cut at the recorded head (its first 11 lines), with the
  same data and environment.
- Its result digest equals the one the shared ledger recorded
  (`c15073642536eb4915e20a4dc3fa70a232b023846b784b8974b557a17ed0d072`).

### Holdout: not run

The hypothesis did not pass development, so per the plan it is not scored on
the holdout. The holdout phase was deliberately not executed, as in v1:

- It would score nothing.
- A holdout record would block those dates for future plans.

The kill rule applies:

- H1 is not re-tuned and is not re-tested on 2017-01-01 to 2026-06-30 in any
  form. "It nearly passed" is exactly the selection the protocol exists to
  stop.
- The only clean follow-up for this exact book is forward paper data
  collected after 2026-10-09 under a new decision record. At a net Sharpe
  ratio near 0.4 that takes many years: about 25 years for even odds of
  t >= 2.

### Verdict

H1_XS_REAL_VALUE_5Y is REJECTED at development (deflated Sharpe ratio 0.77
against 0.95). No daily FX book is promoted to paper or demo work by this
study.
