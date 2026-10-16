"""Predeclared daily FX study plans (research only).

A plan is frozen to a JSON file with ``runner freeze`` before any of its
results exist; every later run rebuilds the plan from this module and refuses
to start unless it matches the frozen file byte for byte. Changing anything
here therefore makes a new plan with a new hash: it never edits a frozen one.
See docs/research/daily-fx-slow-premia-predeclared-v1.md.
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
            "test_data/short-term-interest.csv); they end in 2020-06, JPY starts 2002-04, so H2 and H3 "
            "can only be scored to 2020-06-30 and their development starts in 2002-05.",
            "Risk invariants of the bot: 0.5% risk to the stop per position, 5% open risk, 3% net USD risk, "
            "10 positions, 3% daily and 5% floating loss halts; catastrophe stop at 2.5 monthly sigmas and "
            "take-profit at 3x the stop distance, checked on daily closes.",
            "Hypotheses chosen knowing published full-sample results; only forward paper data is truly clean.",
            "No verdict authorises execution; execution stays removed (release-lock ADR).",
        ),
    )
