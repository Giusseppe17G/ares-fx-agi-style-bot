# Pre-registration: daily FX real value v2

Status: DRAFT (not yet frozen). Research only; no verdict of this study
authorises execution (release-lock ADR). Decision record:
`docs/decisions/2026-10-23-daily-fx-real-value-v2-study.md`.

- Plan: `real_value_v2` in `src/python/agi_style_forex_bot_mt5/research/daily_fx/plans.py`.
- Frozen plan file: `docs/research/daily_fx_real_value_v2/plan.json` (written by `runner freeze`).
- Plan hash (sha256 of the canonical plan JSON): PENDING.
- Engine hash (sha256 of the engine sources): PENDING.
- Environment: PENDING.

Any change to the code, data, parameters or gates gives a different hash, and
the runner refuses it. A new idea needs a new plan, scored only on data that
no plan has scored.

## Question

Inside the bot's own risk invariants, after realistic costs and counting
every trial of the research programme, do the G10 currencies that are cheap
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
  1 July of Y+1. The last year in the file is 2024, so the signal is
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
  distinct and none is the identity. The books have the same turnover and
  sizing but hold the wrong currencies.
- **Time-shifted signal:** 200 copies of the signal circularly shifted by
  distinct offsets of at least 1,435 + 21 + 1 rows in both directions (gated:
  value claims timing).
- **Reported only:** the flipped signal, doubled costs, and the t of
  non-overlapping 21-row returns.

## Development gates (all must hold)

| Check | Threshold |
|---|---|
| Annualised net Sharpe | >= 0.3 |
| Newey-West t-statistic of the mean | >= 2.0 |
| Holm-adjusted p (1 - PSR vs 0), one hypothesis | <= 0.05 |
| Deflated Sharpe ratio over the programme: v1's 7 trials from the ledger plus this one (8). Variance of the trial Sharpes floored at 1/(n-1); each trial on its own window | >= 0.95 |
| PBO | not applicable: one predeclared configuration, no selection |
| Hansen SPA_c p | <= 0.05 |
| Share of permuted-currency books at least as good | <= 0.05 |
| Share of time-shifted books at least as good | <= 0.05 |
| Net Sharpe with doubled costs | > 0 |
| Maximum drawdown | < 12% |
| Largest single-currency share of gross profit | <= 50% |
| Net Sharpe in each subperiod (1985-04 to 1998-12, 1999-01 to 2016-12) | > 0 |

## Holdout verdicts

- `REJECTED` unless the holdout Sharpe ratio and the Sharpe ratio with
  doubled costs are positive and the drawdown stays below 12%.
- `PASSED_RESEARCH` if, in addition, the holdout Newey-West t is at least
  2.0. v1's condition "development PBO <= 0.10" is not applicable to a
  single configuration and is replaced by the programme-wide deflated Sharpe
  ratio of development.
- `WATCHLIST` otherwise.
- Every verdict is **spot-only**. Before any paper design, a pass must be
  confirmed with the broker's real swaps (`--mode capture-swap-snapshot`).

## Power, written before any result

Synthetic Student-t(5) daily returns with the same gates
(`edge_statistics`, v1's seven trial Sharpe ratios from the ledger, 400
draws per row):

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
- **Small absolute returns.** Under the invariants the book's volatility is
  about 2-4% a year, so even a real premium earns little.

## Results

Filled in after the runs, without editing anything above.
