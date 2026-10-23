# Pre-registration: forward paper tracking of the v2 real-value book

Status: FROZEN on 2026-10-23, before the first forward day (2026-10-26).
Re-frozen the same day, still before any forward day, after a PR review found
that sealed closes were not compared on replay. The first freeze (plan
`1515edcd…`, commit b4d54be) was never run on broker data and is superseded.
Research only; no outcome authorises execution (release-lock ADR). Decision record:
`docs/decisions/2026-10-23-daily-fx-value-forward-paper.md`.

- Plan: `value_forward_v1` in `src/python/agi_style_forex_bot_mt5/research/daily_fx/plans.py`.
- Frozen plan file: `docs/research/daily_fx_value_forward_v1/plan.json` (written by `forward_runner freeze`).
- Plan hash: `0da01b7ad0ff9307c95a8c4414160c53dbbe1a4caceecc1584e79510d4693fe2`.
- Engine hash (study engine, `forward.py`, `forward_runner.py`, `broker_swap_snapshot.py`, `core/instruments/registry.py`): `875c04e8ec6c04a5176e78df47d290cf4138ce81bce1bb974ea9786b3896cc83`.
- Code commit to run the tracker from: PENDING (the re-freeze commit).

## Question

Does plan v2's five-year real-value book earn money on the operator's own
broker? The test runs on days that did not exist when the book was frozen,
first with the study's conservative costs and then with the broker's real
swap.

## The book (unchanged from plan v2, hash `e8831946`)

- **Universe.** AUD, CAD, CHF, DKK, GBP, JPY, NOK, NZD and SEK vs USD, with
  USD as a tenth ranked currency.
- **Signal.** The score is minus the five-year real appreciation: the log
  price vs its mean 4.5-5.5 years earlier, plus five published years of CPI
  inflation minus US inflation. The book is long the 3 cheapest and short the
  3 dearest.
- **Sizing.** 0.5% of equity at risk to each position's stop.
- **Rebalancing.** Every 21 rows, executed the next day.
- **The bot's invariants:**
  - 5% open risk;
  - 3% net USD risk;
  - 10 positions;
  - SL and TP on every position;
  - 3% daily and 5% floating loss halts.
- **Costs.**
  - One-way bps: AUD 1.2, CAD 1.2, CHF 1.5, DKK 3.0, GBP 1.2, JPY 1.0,
    NOK 3.0, NZD 2.0, SEK 3.0.
  - The swap is either 75 bps/yr on gross exposure (primary) or the broker's
    real swap (second series).

## Data

| Input | Source | Rule |
|---|---|---|
| Daily prices | The operator's MT5 D1 exports of AUDUSD, USDCAD, USDCHF, USDDKK, GBPUSD, USDJPY, USDNOK, NZDUSD, USDSEK | See below |
| CPI inflation up to 2024 | World Bank FP.CPI.TOTL.ZG, datasets/cpi 3750e450 | sha256 `182baa44…`, as in plan v2 |
| CPI inflation from 2025 | World Bank API, downloaded on the operator's machine | A year is used from 1 July of the next year. It is taken the first time all ten series have it, then fixed. |
| Broker swap | The operator's `capture-swap-snapshot` files | A snapshot applies from the next day, for at most 35 days. Only the `POINTS` swap mode converts. |

Price rules:

- The last bar of every file is dropped.
- The panel runs from exactly 2018-01-02 to the last day every pair has.
- A pair more than one business day behind refuses the run.

## Forward days

From **2026-10-26**, after this plan is frozen. Earlier days only build the
book's state.

## Decision rule (frozen)

There is one look at each anniversary of 2026-10-26, at most ten. At look k
the rule uses the Newey-West t of all primary daily returns before that date.

| Look (years) | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Boundary to confirm | 5.695 | 4.027 | 3.288 | 2.848 | 2.547 | 2.325 | 2.153 | 2.014 | 1.898 | 1.801 |

The boundaries are O'Brien-Fleming for one-sided alpha 0.05 over ten looks,
c = 1.801, simulated with 400,000 Brownian paths. An independent review
found 1.7998 with 2 million paths. The early looks are deliberately hard to
pass.

| Status | Condition |
|---|---|
| CONFIRMED | The t reaches the look's boundary, the broker-swap series covers at least 80% of the days so far, and its total is positive. Otherwise the confirmation is withheld and tracking continues. |
| ABANDONED_FUTILITY | From look 2, the t is at or below -1. |
| ABANDONED_DRAWDOWN | At any time, the primary drawdown reaches 12%. |
| ENDED_WITHOUT_CONFIRMATION | Look 10 passes without a confirmation. |
| ONGOING | Between looks. The statistics are shown, but they decide nothing. |

A final status closes the record.

## Power, written before any forward day

Simulated on Brownian paths with the rule above. These are upper bounds:
swap withholding is not simulated.

| True net Sharpe | 0.0 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.8 | 1.0 |
|---|---|---|---|---|---|---|---|---|
| P(CONFIRMED within 3 years) | 0.00 | 0.00 | 0.00 | 0.00 | 0.01 | 0.01 | 0.03 | 0.06 |
| P(CONFIRMED within 5 years) | 0.01 | 0.02 | 0.03 | 0.05 | 0.08 | 0.12 | 0.23 | 0.39 |
| P(CONFIRMED within 10 years) | 0.05 | 0.15 | 0.23 | 0.33 | 0.45 | 0.57 | 0.79 | 0.92 |

- The development estimate was a net Sharpe of 0.39, before any decay after
  publication. Confirmation in under five years is very unlikely, even if the
  edge is real.
- A book with no edge is confirmed 5% of the time.
- At a true Sharpe of -0.2, about 32% of runs are abandoned within 3 years
  and 57% within 10. The 12% drawdown stop rarely acts at this book's
  volatility, about 1.6% a year.
- A real Sharpe 0.4 book is abandoned for futility about 11% of the time.
- A real but small edge will most likely end without confirmation after ten
  years.

## Integrity

- **Ledger.** Each checkpoint seals, for its new days:
  - primary returns;
  - broker-swap returns;
  - every close not yet sealed (the first checkpoint seals all closes from
    2018-01-02);
  - the decisions;
  - the fixed inflation years;
  - the sha256 of every input file.
- **Refusals.** A run refuses, appending nothing:

  | Code | Cause |
  |---|---|
  | `FORWARD_HISTORY_CHANGED` | A recomputed primary return differs by more than 1e-10, a sealed close by more than a relative 1e-12, or a decision differs. |
  | `ENGINE_CHANGED` or `PLAN_MISMATCH` | The code or the plan changed. Run from the pinned commit. |
  | `INFLATION_BASE_CHANGED` | The pinned inflation file differs. |
  | `LEDGER_MISMATCH` | The ledger belongs to another plan. |
  | `PRICES_STALE`, `PRICES_TOO_SHORT` or `PRICES_MISSING` | The price exports are stale, too short or missing. |

- **Swap values of sealed days** come from the ledger. A snapshot that
  claims to predate the last checkpoint is ignored unless that checkpoint saw
  it.
- **Late runs.** The rule is deterministic, so a late run chooses nothing.
  Each decision records whether it was sealed after its execution day.
- **External anchor.**
  - Locally, the chain detects edits, but not a truncated or restarted
    ledger.
  - The operator sends the ledger at least every quarter and at each look,
    and it is committed under `docs/research/daily_fx_value_forward_v1/`.
  - The broker data and the inflation download are trusted.

## What an outcome allows

- **CONFIRMED.** Only allows writing a decision record about live trading.
  AGENTS.md keeps live trading out of scope, and its conditions still apply:
  - `DEMO_ONLY`;
  - `LIVE_TRADING_APPROVED`;
  - an account whitelist;
  - an approved ADR.
- **Any other outcome.** No money is put on this book.

## Results

Checkpoints are kept in the operator's ledger, and committed copies are
under `docs/research/daily_fx_value_forward_v1/`. A summary is added here at
each annual look, without editing anything above.
