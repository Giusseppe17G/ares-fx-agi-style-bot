# Pre-registration: daily FX slow premia v1

Status: FROZEN on 2026-10-17 at commit ebb61b1, before any result of this
plan existed. Research only; no
verdict of this study authorises execution (release-lock ADR). Decision
record: `docs/decisions/2026-10-16-daily-fx-slow-premia-study.md`.

- Plan: `slow_premia_v1` in `src/python/agi_style_forex_bot_mt5/research/daily_fx/plans.py`.
- Frozen plan file: `docs/research/daily_fx_slow_premia_v1/plan.json` (written by `runner freeze`).
- Plan hash (sha256 of the canonical plan JSON): `82e80e9d8acdb6d071744aaea9f67bde9855aefa45ababefc088564b438557b9`.
- Engine hash (sha256 of the engine sources): `62e730be23f3e76df2a44ec74c3f0f18b4f6af4fc5d6bdc1eddc3e2179859f60`
- Environment: Python 3.14.4, numpy 2.4.4, pandas 3.0.2..

Any change to the code, data, parameters or gates gives a different hash, and
the runner refuses it. A new idea needs a new plan, scored only on data that
no plan has seen (in practice: forward paper data).

## Question

Inside the bot's own risk invariants and after realistic costs, does a slow
FX premium on the G10 currencies against USD earn a positive return that
survives multiple-testing corrections, random and time-shifted controls, a
cost stress and an untouched holdout?

## Data

| Input | Source | Pin | sha256 |
|---|---|---|---|
| Daily prices | FRED H.10 noon New York rates, github.com/datasets/exchange-rates `data/daily.csv` | commit c023dd8b8f87 | `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa` |
| Monthly 3-month rates | OECD short-term interest rates, nautilus_trader `test_data/short-term-interest.csv` | commit 5b1b5b8c5ad9 | `9dff9bbb970b244574a8b8cd841abf4257e924f5c3e413f318eb13afe7620303` |

- Every H.10 series is units of currency per USD (the dataset README is
  wrong for four of them) and is inverted. Prices start on 1999-01-04 (EUR)
  and end on 2026-10-09.
- Rates: JPY starts in 2002-04; JPY and SEK end in 2020-05, the others in
  2020-06. A monthly average is used only during the following month, and a
  missing month ends the simulation. Carry hypotheses therefore start in
  2002-05 and cannot be scored after 2020-06-30.
- A loaded price panel must match known market levels on 2020-01-02 within
  5% (catches an inverted series); a run of five identical published values
  is rejected as a stale feed.
- The data stay outside the repository (gitignored `data/historical/`).
- Caveat: noon rates are not tradable prices; execution realism needs broker
  D1 bars, which this plan does not use.

## Universe and periods

- Currencies vs USD: EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, NOK.
- Development: 1999-01-01 to 2016-12-31 (the engine's warm-up uses the first
  year). Development code never receives a later price or rate.
- Holdout: 2017-01-01 to 2026-10-09, scored once, only for hypotheses that
  pass every development gate. Carry hypotheses: to 2020-06-30.

## Hypotheses and trials (7 in total)

| Id | Primary | Declared variants | Earns carry | Timing claim |
|---|---|---|---|---|
| H1_TSMOM_12M | sign of the 12-month return | 6-month, 3-month, mean of 3/6/12-month signs | no (spot only; swap mark-up charged) | yes |
| H2_BLEND_TSMOM_CARRY | mean of the 12-month trend sign and the rate-differential sign | 6-month trend in the blend | yes | yes |
| H3_TS_CARRY | sign of the previous month's rate differential vs USD | none | yes | no |

Common mechanics: per-currency EWMA volatility (span 60), book volatility
target 10% before the invariants, gross leverage cap 3, rebalance every 21
trading days, decision at day d and execution at the close of d + 1. Carry
and the swap mark-up accrue by calendar days; statistics are annualised with
the observed number of rows per year.

## Risk invariants (the bot's limits)

0.5% risk to the stop per position; 5% open risk; 3% net risk on the shared
USD leg; at most 10 positions; catastrophe stop at 2.5 rebalance-period
sigmas and take-profit at 3x the stop distance, checked on daily closes; on a
day whose loss reached 3%, or while open positions are down 5%, only
reductions; re-entry at the next rebalance. Because positions drift, every
live position is resized at each rebalance and its entry, stop and
take-profit re-anchor there, so under these settings the take-profit and
the loss halts rarely or never engage (stated before any result).

## Costs

One-way bps of notional: EUR 1.0, JPY 1.0, GBP 1.2, CHF 1.5, CAD 1.2,
AUD 1.2, NZD 2.0, SEK 3.0, NOK 3.0 (about twice an ECN half spread plus
3.5 USD per lot per side and one point of slippage), plus a 75 bps a year
swap mark-up on gross exposure. Stress: all costs doubled.

## Controls

- No trade: PSR against a zero Sharpe and SPA_c against zero.
- 200 random-sign books with the same sizing, limits and costs, whose signs
  flip at a rebalance as often as the hypothesis' own signal does (same
  turnover).
- 200 copies of the hypothesis' own signal circularly shifted in time by
  distinct offsets of at least a look-back plus a holding period (same
  turnover, no alignment with returns). Gated only for hypotheses with a timing claim; reported for H3,
  whose nearly static signal keeps its exposure when shifted.
- The flipped signal, each style alone (H1 and H3), doubled costs.

## Development gates (all must hold)

| Check | Threshold |
|---|---|
| Annualised net Sharpe | >= 0.3 |
| Newey-West t-statistic of the mean | >= 2.0 |
| Holm-adjusted p (1 - PSR vs 0) across H1-H3 | <= 0.05 |
| Deflated Sharpe ratio over the 7 trials (each on its own window) | >= 0.95 |
| PBO by CSCV (16 blocks) over the 7 trials | <= 0.30 |
| Hansen SPA_c p over the 7 trials (2,000 bootstraps) | <= 0.05 |
| Share of random-sign books at least as good | <= 0.05 |
| Share of time-shifted books at least as good (timing claims) | <= 0.05 |
| Net Sharpe with doubled costs | > 0 |
| Maximum drawdown | < 12% |
| Largest single-currency share of gross profit | <= 50% |

## Holdout verdicts

- `REJECTED` unless the holdout Sharpe and the Sharpe with doubled costs are
  positive and the drawdown stays below 12%.
- `PASSED_RESEARCH` if, in addition, the holdout Newey-West t is at least 2.0
  and the development PBO is at most 0.10.
- `WATCHLIST` otherwise.

Power warning (written before any result): over about 9.75 holdout years a
true Sharpe of 0.5 reaches t >= 2.0 only about a third of the time, and the
carry hypotheses have only 3.5 holdout years. `WATCHLIST` is the realistic
best case for a real but small premium.

## Holdout protection

- The shared trial ledger docs/research/trial_ledger.jsonl (hash-chained)
  records every trial, control, development summary and holdout result, and
  is committed after each phase.
- The holdout reads which hypotheses proceed, and the PBO, from the ledger;
  the development file must match the digest the ledger recorded.
- The ledger refuses a second development or holdout of this plan, any plan
  whose dates overlap a holdout already scored (on any price file), and a
  holdout whose dates another plan already used for development.
- The runner writes development.json and holdout.json next to the plan file
  and refuses to run the holdout when holdout.json exists.
- The plan binds the Python, numpy and pandas versions; a run on other
  versions is refused.
- Known limit: the hash chain uses no secret, so a fresh or rewritten ledger
  file would bypass these checks; the committed git history of the shared
  ledger is the real protection.

## Kill rule

A `REJECTED` hypothesis is not re-tuned and its holdout is never reused. Any
follow-up is a new plan scored on data no plan has seen.

## Honest caveats

- These hypotheses were chosen knowing published full-sample results
  (including post-2008 weakness of FX momentum). Only forward paper data is
  truly clean.
- Under the invariants the book's volatility is about 2-4% a year, so even a
  real premium earns little in absolute terms.

## Results

Filled in after the runs, without editing anything above. The development
result was written by the runner to
`docs/research/daily_fx_slow_premia_v1/development.json` and every trial,
control and summary to the shared ledger `docs/research/trial_ledger.jsonl`
(11 records, chain verified).

### Development (run once on 2026-10-17, commit b264293): all REJECTED

Common window 2002-05-02 to 2016-12-30 (3,827 days); H1 from 2000. Seven
trials: PBO 0.69 (gate <= 0.30), SPA_c p 0.15 (gate <= 0.05).

| | H1 trend 12m | H2 blend | H3 carry |
|---|---|---|---|
| Net Sharpe (gate >= 0.3) | 0.14 | 0.17 | -0.11 |
| Gross Sharpe (before costs and swap mark-up) | 0.29 | 0.27 | 0.04 |
| Net annual return | 0.46% | 0.42% | -0.36% |
| Annual volatility | 3.2% | 2.6% | 3.1% |
| Max drawdown (gate < 12%) | 15.5% | 14.4% | 26.8% |
| Newey-West t (gate >= 2.0) | 0.57 | 0.62 | -0.41 |
| Holm-adjusted p (gate <= 0.05) | 0.79 | 0.79 | 0.79 |
| Deflated Sharpe (gate >= 0.95) | 0.37 | 0.41 | 0.10 |
| Share of random books as good (gate <= 0.05) | 0.065 | 0.10 | 0.37 |
| Share of time-shifted books as good (gate <= 0.05) | 0.065 | 0.27 | 0.69 (not gated) |
| Sharpe with doubled costs (gate > 0) | 0.001 | 0.06 | -0.27 |
| Gates failed | 9 of 11 | 9 of 11 | 10 of 11 |

Reading, without changing any verdict:

- No hypothesis comes close: the best t-statistic is 0.62 against a bar of
  2.0. The declared variants (H1 at 6 and 3 months, the 3/6/12 mix, H2 at
  6 months) reach net Sharpes of 0.23-0.40; with PBO 0.69, picking the best
  of them would most likely be overfitting, and none would reach t >= 2.
- Trend made money in 2000-2004 and 2007-2008 and lost from 2009 to 2013,
  in line with the published post-2008 weakness of FX momentum. Carry lost
  9.8% in 2008 and 7.8% in 2014.
- Under the bot's invariants the book is small (gross exposure about 0.3-0.6
  of equity, volatility about 3%), so the swap mark-up on gross exposure
  takes about half of H1's gross return. A premium of this size cannot pay
  retail financing at these position sizes.
- The take-profit never triggered and no rebalance was blocked by a loss
  halt, as stated before the run; stops triggered 15, 29 and 53 times.

Reproduction check (2026-10-17): the development was re-run from a copy of
the frozen plan into a fresh ledger with the same data and environment; its
result digest equals the one the shared ledger recorded
(`aac13d4236565b656ae7d048d2827271abde8e7d74b191243908760dccab8cd5`).

### Holdout: not run

No hypothesis passed development, so per the plan none is scored on the
holdout. The holdout phase was deliberately not executed: it would score
nothing, and recording a holdout window in the shared ledger would block
those dates for future plans although no plan has looked at them. The
2017-01-01 to 2026-10-09 data remain unscored by any plan.

### Verdict

H1, H2 and H3 are REJECTED (kill rule: not re-tuned, not re-tested on these
data). No daily FX book is promoted to paper or demo work by this study.
