# Pure native closed-bar window

Accepted scope: canonical data selection only, under PROJECT_SPEC section 17.8.
This module is not wired to the EA and cannot authorize execution. It changes
neither Python production code nor the existing native observer.

`NativeSelectClosedBars(request, bars, result)` consumes explicit UTC millisecond
timestamps and canonical OHLC/volume/spread values. Symbol and M5/M15/H1 identity
apply to the entire array. The caller must establish UTC provenance and choose
the volume definition; neither is inferred here. `MqlRates` distinguishes tick
volume from trade volume and labels its time as the period start, so it is not
silently accepted as this canonical contract. See the official
[MqlRates definition](https://www.mql5.com/en/docs/constants/structures/mqlrates).

The selector accepts a clock interval with resolution 1 or 1000 milliseconds.
Its inclusive upper endpoint is `clock_start_utc_msc + resolution - 1`. A
snapshot after the interval's start rejects, including an ambiguously future
snapshot inside the same second. Snapshot age and latest closed-bar age use
the upper endpoint. This cannot manufacture finer clock resolution. The native
observer has its own earlier temporal policy and is deliberately unchanged.

All timestamps are positive and bounded by 3000-12-31 23:59:59.999 UTC. Bar
closing time and clock upper endpoint must fit that range before arithmetic.
The bound follows MQL5's documented
[datetime calendar](https://www.mql5.com/en/docs/basis/types/integer/datetime).

Every input row is validated before returning a window: chronological uniqueness,
nonoverlapping intervals, valid calendar, finite positive coherent OHLC, and
finite nonnegative volume/spread. Gaps, zero volume and zero spread remain
unchanged. Zero spread is not cost verification. Bars closing after the
snapshot are counted and excluded only after their input values pass validation.
No sorting, deduplication, padding, price normalization or indicator calculation
occurs. Timeframe aliases require the separately invoked normalizer.

The semantic Python references are `closed_strategy_bars` and the shared
decision pipeline's temporal validation. Native validation additionally rejects
malformed excluded rows, overlapping intervals and timestamps outside its own
calendar. Therefore fixtures distinguish comparable semantics from stricter
native rejections; this is not a claim of universal parity.

`NativeClosedBarResult` owns a dynamic `closed_bars[]` array. This avoids callers
passing a fixed output buffer that cannot be emptied. MQL5 supports dynamic
arrays within structs, with initialization handled by its implicit constructor;
see [structure initialization](https://www.mql5.com/en/docs/basis/types/classes).
A local input copy permits reusing the previous result window as the next input.
The copy and output reservations are checked. Every rejection releases the
output through [ArrayFree](https://www.mql5.com/en/docs/array/arrayfree), resets
validity, counts and availability, and preserves false execution/parity flags.
Only input count and already validated canonical timeframe remain diagnostic.

The pure core contains no market/account acquisition, clock reads, terminal
calls, network, file operations, signal/risk approvals or order capabilities.
Fixtures are compiled into a separate script; no runtime history adapter is
introduced. Compiling that script does not execute its assertions. Runtime
memory failure, actual MQL assertion execution, source authentication and
terminal/broker acquisition remain unverified. No dependency is added.
