"""Validation helpers: baselines a candidate must beat before it counts as an edge."""

from .baselines import BaselineResult, buy_and_hold, compare_to_baselines, permuted_signal, random_entry

__all__ = ["BaselineResult", "buy_and_hold", "compare_to_baselines", "permuted_signal", "random_entry"]
