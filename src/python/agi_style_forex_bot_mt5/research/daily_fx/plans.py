"""Predeclared daily FX study plans (research only).

A plan is frozen to a JSON file with ``runner freeze`` before any of its
results exist; every later run rebuilds the plan from this module and refuses
to start unless it matches the frozen file byte for byte. Changing anything
here therefore makes a new plan with a new hash: it never edits a frozen one.
See docs/research/daily-fx-slow-premia-predeclared-v1.md and
docs/research/daily-fx-real-value-predeclared-v2.md.
"""

from __future__ import annotations

from .portfolio import CostModel, PortfolioConfig, RiskLimits
from .study import Acceptance, DataBinding, Hypothesis, StudyPlan

G10_VS_USD = ("EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK")

# One-way cost in bps of notional: about twice an ECN account's half spread,
# 3.5 USD per lot per side commission and one point of slippage. The swap
# mark-up is charged on gross exposure on top of any carry the book earns.
SLOW_PREMIA_COSTS = CostModel(
    {"EUR": 1.0, "JPY": 1.0, "GBP": 1.2, "CHF": 1.5, "CAD": 1.2, "AUD": 1.2, "NZD": 2.0, "SEK": 3.0, "NOK": 3.0},
    financing_bps_per_year=75.0,
)


def slow_premia_v1(price_sha256: str, rates_sha256: str) -> StudyPlan:
    """Slow FX premia inside the bot's invariants: 12-month trend, carry and their blend."""

    trend = PortfolioConfig(signal="tsmom", lookbacks=(252,), rebalance_days=21, execution_lag_days=1)
    blend = PortfolioConfig(signal="blend", lookbacks=(252,), rebalance_days=21, execution_lag_days=1)
    carry = PortfolioConfig(signal="tscarry", lookbacks=(252,), rebalance_days=21, execution_lag_days=1)
    hypotheses = (
        Hypothesis(
            "H1_TSMOM_12M",
            "Each currency vs USD is long when its 12-month return is positive and short otherwise "
            "(Moskowitz, Ooi & Pedersen 2012). Spot returns only: the carry earned or paid by the "
            "position is not credited, the swap mark-up is charged.",
            trend,
            (PortfolioConfig(signal="tsmom", lookbacks=(126,)), PortfolioConfig(signal="tsmom", lookbacks=(63,)),
             PortfolioConfig(signal="tsmom", lookbacks=(63, 126, 252))),
        ),
        Hypothesis(
            "H2_BLEND_TSMOM_CARRY",
            "Equal mix of the 12-month trend sign and the sign of the previous month's 3-month rate "
            "differential vs USD; returns include the rate differential accrued daily.",
            blend,
            (PortfolioConfig(signal="blend", lookbacks=(126,)),),
            carry_accrual=True,
        ),
        Hypothesis(
            "H3_TS_CARRY",
            "Long each currency whose previous-month 3-month rate exceeds the USD rate, short otherwise "
            "(Lustig, Roussanov & Verdelhan 2011; Koijen et al. 2018); returns include the carry.",
            carry,
            carry_accrual=True,
            timing_claim=False,
        ),
    )
    return StudyPlan(
        name="daily_fx_slow_premia_v1",
        currencies=G10_VS_USD,
        development=("1999-01-01", "2016-12-31"),
        holdout=("2017-01-01", "2026-10-09"),
        hypotheses=hypotheses,
        costs=SLOW_PREMIA_COSTS,
        data=DataBinding("fred_h10_daily", price_sha256, rates_sha256),
        limits=RiskLimits(),
        cost_stress_factor=2.0,
        random_replicas=200,
        pbo_blocks=16,
        spa_bootstraps=2000,
        acceptance=Acceptance(),
        notes=(
            "Prices: FRED H.10 noon New York rates, github.com/datasets/exchange-rates commit c023dd8b8f87, "
            "data/daily.csv; every series is currency per USD and is inverted.",
            "Rates: OECD monthly 3-month interbank rates (nautilus_trader commit 5b1b5b8c5ad9, "
            "test_data/short-term-interest.csv). A month's average is used only during the next month. "
            "JPY starts in 2002-04 and JPY and SEK end in 2020-05 (the others in 2020-06), so H2 and H3 "
            "start in 2002-05 and can only be scored to 2020-06-30.",
            "H1 is spot only: it is not credited the rate differential its positions earn or pay.",
            "Under the plan defaults the take-profit and the loss halts rarely or never engage: entries, "
            "stops and take-profits re-anchor at every rebalance because positions are resized there.",
            "Risk invariants of the bot: 0.5% risk to the stop per position, 5% open risk, 3% net USD risk, "
            "10 positions, 3% daily and 5% floating loss halts; catastrophe stop at 2.5 monthly sigmas and "
            "take-profit at 3x the stop distance, checked on daily closes.",
            "Hypotheses chosen knowing published full-sample results; only forward paper data is truly clean.",
            "No verdict authorises execution; execution stays removed (release-lock ADR).",
        ),
    )


# v2 universe: the G10 currencies with prices since 1971. DKK stands for the
# DEM/EUR bloc because EUR prices only start in 1999.
REAL_VALUE_CURRENCIES = ("AUD", "CAD", "CHF", "DKK", "GBP", "JPY", "NOK", "NZD", "SEK")
# The first price row read: after the last 1970s peg run (1974-11-18) and 5.5
# years plus the volatility warm-up before the development start.
REAL_VALUE_PRICE_START = "1979-01-02"
REAL_VALUE_COSTS = CostModel(
    {"AUD": 1.2, "CAD": 1.2, "CHF": 1.5, "DKK": 3.0, "GBP": 1.2, "JPY": 1.0, "NOK": 3.0, "NZD": 2.0, "SEK": 3.0},
    financing_bps_per_year=75.0,
)


def real_value_v2(price_sha256: str, inflation_sha256: str) -> StudyPlan:
    """Cross-sectional five-year real exchange rate value, spot only, inside the bot's invariants."""

    value = PortfolioConfig(signal="xsvalue", lookbacks=(1435,), average_rows=261, inflation_years=5, xs_top=3,
                            sizing="equal_risk", rebalance_days=21, execution_lag_days=1)
    hypothesis = Hypothesis(
        "H1_XS_REAL_VALUE_5Y",
        "Currency value (Asness, Moskowitz & Pedersen 2013): the score of each currency is minus its real "
        "appreciation vs USD over about five years, i.e. the log price on the decision day minus its mean over "
        "the year that ended 4.5 years earlier, plus the last five published years of its CPI inflation minus "
        "US CPI inflation. The nine currencies and USD (score zero) are ranked; the three cheapest are bought "
        "and the three dearest sold against USD, each at 0.5% of equity to its stop. Spot returns only: the "
        "rate differential is not credited, the swap mark-up is charged.",
        value,
        carry_accrual=False,
        timing_claim=True,
        subperiods=(("1985-04-01", "1998-12-31"), ("1999-01-01", "2016-12-31")),
    )
    return StudyPlan(
        name="daily_fx_real_value_v2",
        currencies=REAL_VALUE_CURRENCIES,
        development=("1985-04-01", "2016-12-31"),
        holdout=("2017-01-01", "2026-06-30"),
        hypotheses=(hypothesis,),
        costs=REAL_VALUE_COSTS,
        data=DataBinding("fred_h10_daily", price_sha256, inflation_sha256=inflation_sha256),
        limits=RiskLimits(),
        cost_stress_factor=2.0,
        random_replicas=200,
        pbo_blocks=16,
        spa_bootstraps=2000,
        acceptance=Acceptance(),
        price_start=REAL_VALUE_PRICE_START,
        program_trials=7,
        notes=(
            "Prices: FRED H.10 noon New York rates, github.com/datasets/exchange-rates commit c023dd8b8f87, "
            "data/daily.csv (the file v1 used), read from 1979-01-02; every series is currency per USD and is "
            "inverted.",
            "Inflation: World Bank FP.CPI.TOTL.ZG via github.com/datasets/cpi commit 3750e450, data/cpi.csv, whose "
            "CPI column is annual % CPI inflation (not an index). Year Y is used from 1 July of Y+1; the last year "
            "is 2024, so the signal is complete up to 2026-06-30 and the holdout ends there.",
            "Spot only: no rate file covers 2017-2026 for all ten currencies, so the rate differential is not "
            "credited and the 75 bps/yr swap mark-up is charged on gross exposure. Any verdict is spot-only and "
            "must be confirmed with the broker's real swaps (swap snapshot) before a paper path is designed.",
            "Development starts on 1985-04-01, after the NZD float (1985-03-04). SEK and NOK basket pegs (to 1992) "
            "and DKK in the EMS are kept; capital controls and realignments before 1990 make some development "
            "P&L hard to achieve.",
            "The deflated Sharpe ratio counts v1's 7 development trials from the shared ledger plus this one, with "
            "the variance of the trial Sharpes floored at 1/(n-1). PBO is not applicable to a single predeclared "
            "configuration, so the holdout's PBO condition is replaced by that deflated Sharpe ratio.",
            "Controls: the same ranking given to 200 distinct permutations of the ten currencies (same turnover, "
            "wrong currencies), and the signal shifted in time by at least 5.5 years plus a holding period (gated: "
            "value claims timing).",
            "Each development subperiod (1985-04 to 1998-12, 1999-01 to 2016-12) must keep a positive net Sharpe.",
            "Chosen knowing the published results (AMP 2013; Menkhoff, Sarno, Schmeling & Schrimpf 2017) and the "
            "broad FX moves of 2017-2025 (the 2021-2024 yen slump, the 2022 USD rally); every parameter comes from "
            "AMP 2013 or v1, none was tuned to them.",
            "Risk invariants of the bot: 0.5% risk to the stop per position, 5% open risk, 3% net USD risk, "
            "10 positions, 3% daily and 5% floating loss halts; catastrophe stop at 2.5 monthly sigmas and "
            "take-profit at 3x the stop distance, checked on daily closes.",
            "No verdict authorises execution; execution stays removed (release-lock ADR).",
        ),
    )
