# Reject invalid arithmetic in approximate VWAP

Scope: Python feature preparation and its research/forward callers. No orders,
strategy parameters, indicator seeds or dependencies changed. PROJECT_SPEC 17.10
defines the compatibility restriction.

Finite positive OHLC and finite nonnegative volume do not guarantee finite
products or cumulative sums. Previously `fillna(typical_price)` hid some arithmetic
failures as a plausible price; other cases returned infinity or zero. For 220
prices 10.00 through 12.19 with volume 1e308, the old final value was 12.19 despite
overflow, rather than a valid cumulative VWAP. Positive int64 OHLC 4e18 also
wrapped during the three-price sum and returned a negative value.

The function now converts OHLC to floating point before addition and checks
typical prices, weighted prices, cumulative volumes/values and final results.
Unrepresentable intermediates and a positive product underflowing to zero raise
MarketDataError. Only exactly zero cumulative volume receives the existing
typical-price fallback. Later zero-volume rows retain the accumulated VWAP.
No rescaling or higher-precision fallback invents support for extreme inputs.
Used fields require normalized real numeric dtypes. A separate reviewer
reproduced loss of imaginary volume and positive Decimal volume becoming zero
during float conversion. Complex, boolean and object dtypes now reject before
conversion; twelve parameterized regressions cover the four used columns.

The ordinary cumulative formula and index are preserved. Seed definitions for
EMA, RSI and ATR are unchanged. This does not authenticate volume or solve the
difference between tick volume and traded volume; VWAP remains approximate.

Verification: eight of eleven new regression cases failed against the previous
implementation (six finite-input numeric failures, int64 wrapping and feature
bundle propagation). Tests additionally cover all-zero/initial/later zero volume,
ordinary exact compatibility and prefix causality. MQL runtime is unrelated to
these Python tests. The rejected extremes are synthetic counterexamples, not
observed broker incidents or evidence of financial performance.

An integration regression passes the extreme volume through the actual forward
run with a fake read-only MT5 client and through stateful replay. Forward's
existing acquisition layer records FORWARD_FEATURE_BUILD_FAILED and excludes
the candidate; replay's existing lifecycle halts on MarketDataError. Both keep
audit evidence and produce no decision or trade. Their failure recovery modes
are different; this test does not claim lifecycle parity for the invalid input.
