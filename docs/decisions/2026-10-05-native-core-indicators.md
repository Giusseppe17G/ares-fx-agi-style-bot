# Pure native core indicators

Accepted scope: `native_core_indicators_v1`, under PROJECT_SPEC section 17.9.
This is deterministic preparation of five indicator values: EMA20, EMA50,
EMA200, RSI14 and ATR14. It does not implement a strategy, regime classifier,
scoring, position sizing, VWAP or trading authorization. The EA is unchanged.

`NativeCalculateCoreIndicators(request, bars, result)` receives the same explicit
canonical data and time contract as the closed-bar selector. Each call invokes
`NativeSelectClosedBars` with its own local result. An externally supplied
success flag cannot bypass validation. All stricter native selection checks,
including invalid excluded rows, nonoverlapping intervals and conservative
clock resolution, remain in force. The selector's rejection reason propagates.

The calculator requires both the request's minimum and at least 200 selected
bars. It processes the complete selected prefix from its first observation;
it neither truncates the history nor caches state between calls. Gaps do not
insert samples or additional time decay. Changing the history origin may change
the result, so the output records that origin and the observation count. The
research evaluator's 250-bar warmup is a separate downstream policy.

The numerical reference is the repository's actual `ema`, `rsi` and `atr`
functions in `data/indicators.py`, not an assumed terminal indicator formula:

- EMA uses the first close as its seed and alpha `2/(period+1)`.
- ATR starts with the first bar's high minus low. Later true ranges are the
  maximum of high minus low and the absolute high/low distances to the previous
  close. The smoothing alpha is `1/14` and the seed is that first true range.
- RSI seeds gain/loss averages from the first real close difference, at index
  one. There is no fabricated zero difference at index zero and no SMA seed.
  Both averages use alpha `1/14`. Fourteen differences require fifteen closes.
  Zero loss with positive gain produces 100; both zero produce 50; zero gain
  with positive loss produces 0.

The smoother follows `adjust=False`. It preserves an unchanged value when old
and new observations compare equal, as pandas does, avoiding unnecessary
rounding of constant series. Otherwise it uses the weighted numerator divided
by the sum of weights. The recurrence and minimum-observation semantics are
documented in [pandas ewm](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.ewm.html).
The full package is published only when all five values are available; no
partial early EMA/ATR outputs are exposed. ATR zero remains mathematically
valid here and provides no signal or sizing approval.

The scalar `NativeCoreIndicatorResult` contains validity/reason/version,
symbol/timeframe, bars count, history origin, final source/availability,
declared snapshot/clock/resolution, and the five values. All numbers and identity
fields are reset before calculation and on rejection. Only the package version
and rejection reason remain descriptive. Numeric zero in an invalid result
means unavailable, not a measured indicator. Both `execution_authorized` and
`full_pipeline_verified` stay false on every path.
The recorded clock/snapshot remains the caller's declared observation time;
it is never refreshed during publication. Any future consumer must revalidate
freshness at use rather than treating an earlier valid result as current evidence.

Finite validation covers intermediates as well as published values. EMA outputs
must be positive, RSI must be in [0,100], and ATR must be nonnegative. Addition
is guarded before overflow. Weighted multipliers are bounded in (0,1).
Division first requires a positive finite denominator; when that denominator
is below one, a numerator exceeding `DBL_MAX * denominator` rejects before
dividing. MQL5 defines [DBL_MAX](https://www.mql5.com/en/docs/constants/namedconstants/typeconstants)
as its largest finite double. No clamping, epsilon replacement, rescaling or
rounding is used to force an input through a check.

This intentionally rejects an RSI relative-strength quotient that would
overflow even if pandas later maps it to a finite saturated RSI of 100. That
case is a stricter native numeric rejection, not universal numeric parity.
Subnormal behavior and platform/compiler arithmetic remain runtime risks.

The public new rejection codes are `INSUFFICIENT_INDICATOR_WARMUP` and
`INDICATOR_ARITHMETIC_INVALID`; successful publication uses
`CORE_INDICATORS_VALID`. No existing Python function signature, calculation
parameter, native closed-bar contract or execution gate changes.

Shared synthetic fixtures call the existing Python functions and retain their
runtime versions and input history. Comparison budgets are predeclared solely
for those fixtures: EMA/ATR allow 512 ULP of the expected value, exact zero must
stay zero, and RSI allows absolute error 1e-10 on its 0..100 scale. These bounds
are not production thresholds and cannot enable signals. Prefixes, history
origins, warmup boundaries, gaps, constants, extreme values, invalid excluded
rows and rejection after prior success require coverage.

The source author ran the existing native source guards and closed-bar fixture
tests after adding these includes: 132 tests passed. That check does not execute
the new MQL arithmetic. The integration owner compiles the separately owned
indicator harness; its results must distinguish compilation from execution.
No native runtime assertions, terminal handles, account connection, file/network
operations, broker data acquisition or order routes are introduced here.
