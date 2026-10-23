# Daily FX real-value study v2: one spot-only hypothesis deflated over the programme

Date: 2026-10-23. Touches: research and backtesting only
(`src/python/agi_style_forex_bot_mt5/research/`). No strategy, risk,
execution, Expert or production Python behaviour changes. Execution stays
removed (release-lock ADR) and no verdict of this study authorises it.

## Context

Plan v1 (`2026-10-16-daily-fx-slow-premia-study.md`) rejected 12-month
trend, carry and their blend on 1999-2016. Its kill rule forbids re-testing
them on those years, and its holdout (2017 onwards) was never scored. Three
independent design reviews of a follow-up (statistical power, published
evidence, a sceptic) converged on one candidate. Cross-sectional real
exchange rate value (Asness, Moskowitz & Pedersen 2013; Menkhoff, Sarno,
Schmeling & Schrimpf 2017) is:

- the only slow FX premium with long published records that is not one of
  v1's ideas;
- computable from prices and CPI alone;
- close to dollar-neutral.

The reviews also found the binding constraints:

- **Deflated Sharpe ratio.** Counting v1's seven trials, it needs an observed
  t of about 3.1.
- **Swap mark-up.** The 75 bps/yr mark-up on gross exposure costs a long-short
  book about 0.2-0.35 of Sharpe.
- **Data traps:**
  - the World Bank "CPI" file holds annual % inflation, not an index;
  - the OECD monthly rates end in 2020 with holes;
  - the engine's stale-price check refused any panel starting before
    1974-11-19.

## Decision

1. **Signal (`portfolio.py`, `xsvalue`).** On decision day d, each
   currency's score is minus its real appreciation vs USD:
   - log price on d minus the mean log price over the 261 rows (one year)
     that end 4.5 years earlier (rows d-1435 to d-1175);
   - plus the sum, over the last five published years, of
     ln(1 + its CPI inflation) minus ln(1 + US CPI inflation).

   Ranking:
   - USD is ranked with a score of zero.
   - The three highest scores are long and the three lowest short against
     USD. A USD slot leaves its leg to the others, so net USD risk is at most
     one position.
   - Ties go to the ISO code first in alphabetical order.

   Fail-closed rules:
   - Year Y of inflation is used only from 1 July of Y+1.
   - A missing year makes the row incomplete, and the next rebalance
     flattens the book.
2. **Sizing (`sizing="equal_risk"`).** Every position takes exactly the
   per-position risk cap (0.5% of equity) to its stop. `_apply_limits` and
   every invariant and halt are unchanged.
3. **Data (`data.py`).**
   - `load_worldbank_inflation` reads datasets/cpi `data/cpi.csv`. It refuses
     the file unless five known values match within 0.1 pp, which rejects a
     CPI-index vintage and the GDP-deflator file. It also refuses missing
     years inside a series.
   - `load_fred_daily(start=...)` drops rows before the start before any
     check. The 1970s pegs are then never read, and the stale and gap checks
     still apply to every row used.
4. **Study (`study.py`).**
   - **Programme deflation.** `StudyPlan.program_trials` deflates the Sharpe
     ratio over every other plan's development trials in the ledger as well
     as the plan's own. The run refuses a ledger with fewer trials than
     declared. The variance of the trial Sharpes is floored at the null
     sampling variance 1/(n-1), the convention of
     `2026-10-22-deflated-promotion-gate.md`; `edge_statistics` gains
     `min_variance`.
   - **PBO.** A plan with a single configuration records PBO as not
     applicable: there is no selection for it to measure. The holdout's
     promotion condition on PBO is therefore satisfied by the programme-wide
     deflated Sharpe ratio. This relaxes v1's PBO gate only for a plan
     without selection, and is accepted here because the programme
     deflation is stricter than v1's.
   - **Random control.** For a cross-sectional signal it is the same ranking
     given to 200 distinct permutations of the ten currencies: same
     turnover, wrong currencies. Random signs would build directional books
     that are not comparable.
   - **Subperiods.** A hypothesis may declare development subperiods, and
     each must keep a net Sharpe above zero.
   - **Inflation binding.** The plan binds the inflation file's sha256 and
     the first price row, and the run refuses other inputs. Development never
     sees an inflation figure published after its end.
   - **Reporting.** Results report whether carry was credited and the
     Newey-West t of non-overlapping 21-row returns (reported only).
5. **Plan v2 (`plans.py`, `real_value_v2`).**

   | Item | Value |
   |---|---|
   | Hypothesis | one, H1_XS_REAL_VALUE_5Y; no variants |
   | Universe | AUD, CAD, CHF, DKK, GBP, JPY, NOK, NZD, SEK and USD |
   | Prices | read from 1979-01-02 |
   | Development | 1985-04-01 to 2016-12-31 |
   | Holdout | 2017-01-01 to 2026-06-30 (the last day with complete inflation) |
   | P&L | spot only; costs as v1 plus DKK 3.0 bps |
   | Gates | v1's development gates and holdout tiers, plus the subperiod gate; the shift control is gated |
   | Deflation | over v1's 7 trials plus this one |

   It is frozen and pre-registered in
   `docs/research/daily-fx-real-value-predeclared-v2.md` before any of its
   results exist.

## Rejected alternatives

- **Carry accrual from the Global Macro Database's annual rates.** It is
  licensed for non-commercial research and could not be confirmed for this
  use. A carry signal is impossible anyway in the holdout (no full G10
  monthly rates after 2020-04). The plan is spot only, and the label says
  so.
- **Value plus momentum on 1977-1998.** Too little power in 21.5 years. It
  would also raise the deflation benchmark for the value test.
- **PPP-level value.** World Bank PPP levels are revised by 3-11% between
  vintages (look-ahead) and start in 1990.
- **Cross-sectional carry.** No complete G10 monthly rates before 2002 or
  after 2020-04, and it is the closest relative of v1's rejected carry.

## Consequences

- **Low power, stated before any result.** On synthetic returns, the
  development gates pass with probability about 0.06 at a true net Sharpe of
  0.3, 0.17 at 0.4, 0.36 at 0.5 and 0.55 at 0.6. A 9.5-year holdout reaches
  t >= 2 about 0.13, 0.19, 0.34 and 0.43 of the time at the same Sharpes.
  The most likely outcome is a rejection, even if the premium is real.
- **Spot only.** A pass would describe the spot return of a value book. The
  rate differential it would earn or pay is not in the numbers, so a pass
  must be confirmed with the broker's real swaps (`capture-swap-snapshot`)
  before any paper design.
- **v1 reproduction.** The engine hash moves, so plan v1 reproduces only at
  commit b264293 (as already stated). The changes are additive:
  - new fields with defaults on `PortfolioConfig`, `Hypothesis`,
    `Acceptance`, `DataBinding` and `StudyPlan`;
  - new optional arguments on `backtest`, `run_development`, `run_holdout`
    and `deflated_sharpe_ratio`;
  - `runner --rates` is now required only by plans that use rates.
- **What a verdict allows.** `PASSED_RESEARCH` or `WATCHLIST` only allows
  designing a daily paper path with its own ADR. The Strategy Promotion Gate
  (PROJECT_SPEC 12.1) still applies in full.
