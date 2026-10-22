"""Holm-adjusted one-sided significance of mean R for the edge selectors.

docs/decisions/2026-10-22-deflated-promotion-gate.md: PF > 1.10 on 30 trades is
passed by a zero-edge slice often, and almost surely when many slices are
tried. A KEEP now also needs the one-sided t-test of mean R (H0: mean R <= 0)
to stay significant after a Holm step-down adjustment across every row
evaluated in the same selector call. Rows whose test cannot be computed
(counts only, missing or zero dispersion, tiny samples) enter the family with
p = 1: they make the adjustment stricter and never reach KEEP.

Research only: nothing here builds, checks or sends an order.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from ..research.edge_statistics import holm_adjusted

SIGNIFICANCE_ALPHA = 0.05
MIN_SIGNIFICANCE_TRADES = 3
SIGNIFICANCE_COLUMNS = (
    "mean_r_t_stat",
    "mean_r_p_value",
    "holm_adjusted_p_value",
    "holm_family_size",
    "significance_status",
)

_MAX_ITERATIONS = 100_000
_EPSILON = 1e-15
_TINY = 1e-300


def student_t_sf(t_value: float, df: float) -> float:
    """Upper-tail probability P(T >= t) of Student's t with ``df`` degrees of freedom."""

    t = float(t_value)
    freedom = float(df)
    if not math.isfinite(t) or not math.isfinite(freedom) or freedom <= 0.0:
        raise ValueError("t must be finite and df finite and positive")
    # P(|T| >= |t|) = I_x(df/2, 1/2) with x = df / (df + t^2).
    two_sided = _regularized_incomplete_beta(freedom / 2.0, 0.5, freedom / (freedom + t * t))
    upper = 0.5 * two_sided
    return upper if t >= 0.0 else 1.0 - upper


def mean_r_significance(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Per-row significance of mean R, in the frame's row order.

    Needs ``expectancy_r`` (mean R), ``r_multiple_std`` (sample standard
    deviation of R, ddof=1) and ``total_trades`` (or ``trades``). The Holm
    family is every row of ``frame``.
    """

    rows: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        rows.append(_row_test(record))
    adjusted = holm_adjusted([1.0 if row["mean_r_p_value"] is None else row["mean_r_p_value"] for row in rows])
    for row, value in zip(rows, adjusted):
        row["holm_adjusted_p_value"] = float(value)
        row["holm_family_size"] = len(rows)
    return rows


def is_significant(significance: dict[str, Any]) -> bool:
    value = significance.get("holm_adjusted_p_value")
    return isinstance(value, float) and math.isfinite(value) and value <= SIGNIFICANCE_ALPHA


def not_significant_reason(significance: dict[str, Any]) -> str:
    return (
        "mean R not significant after Holm adjustment "
        f"(one-sided adjusted p={significance['holm_adjusted_p_value']:.4g} > {SIGNIFICANCE_ALPHA:g} "
        f"across {significance['holm_family_size']} rows; {significance['significance_status']})"
    )


def _row_test(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"mean_r_t_stat": None, "mean_r_p_value": None}
    if str(record.get("metrics_status", "FULL_EDGE_METRICS")) == "COUNTS_ONLY":
        return {**result, "significance_status": "UNAVAILABLE_COUNTS_ONLY"}
    trades = _number(record.get("total_trades", record.get("trades")))
    mean = _number(record.get("expectancy_r"))
    std = _number(record.get("r_multiple_std"))
    if trades is None or not trades.is_integer():
        return {**result, "significance_status": "UNAVAILABLE_INVALID_METRICS"}
    if trades < MIN_SIGNIFICANCE_TRADES:
        return {**result, "significance_status": "UNAVAILABLE_SMALL_SAMPLE"}
    if mean is None:
        return {**result, "significance_status": "UNAVAILABLE_NO_MEAN"}
    if std is None:
        return {**result, "significance_status": "UNAVAILABLE_NO_DISPERSION"}
    if std <= 0.0:
        return {**result, "significance_status": "UNAVAILABLE_ZERO_DISPERSION"}
    t_value = mean * math.sqrt(trades) / std
    if not math.isfinite(t_value):
        return {**result, "significance_status": "UNAVAILABLE_INVALID_METRICS"}
    return {
        "mean_r_t_stat": t_value,
        "mean_r_p_value": student_t_sf(t_value, trades - 1.0),
        "significance_status": "COMPUTED",
    }


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Continued fraction of the incomplete beta function (modified Lentz)."""

    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) >= _TINY else _TINY)
    h = d
    for m in range(1, _MAX_ITERATIONS + 1):
        m2 = 2.0 * m
        for numerator in (
            m * (b - m) * x / ((qam + m2) * (a + m2)),
            -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2)),
        ):
            d = 1.0 + numerator * d
            d = 1.0 / (d if abs(d) >= _TINY else _TINY)
            c = 1.0 + numerator / c
            c = c if abs(c) >= _TINY else _TINY
            delta = d * c
            h *= delta
        if abs(delta - 1.0) < _EPSILON:
            return h
    raise ValueError("incomplete beta continued fraction did not converge")
