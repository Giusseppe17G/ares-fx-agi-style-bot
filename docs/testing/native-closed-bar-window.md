# Native closed-bar window verification

Scope is `NATIVE_CLOSED_BAR_WINDOW_ONLY`. The selector is isolated from the EA;
`execution_authorized` and `full_pipeline_verified` are always false.

The public API is:

```cpp
bool NativeSelectClosedBars(const NativeClosedBarRequest &request,
                            const NativeClosedBar &bars[],
                            NativeClosedBarResult &result);
bool NativeNormalizeClosedBarTimeframe(const string raw, string &canonical);
```

`NativeClosedBar` fields are `timestamp_utc_msc`, `open`, `high`, `low`, `close`,
`volume`, and `spread_points`. Timestamps mark opening, not availability.
Request fields are `symbol`, canonical `timeframe`, `snapshot_utc_msc`,
`clock_start_utc_msc`, `clock_resolution_msc`, `minimum_bars`, and
`max_snapshot_age_msc`. No request field has an inferred default. Resolution
must be 1 or 1000 milliseconds and maximum snapshot age must be in 1..5000.

Success returns every eligible row unchanged in `result.closed_bars`, with
`closed_count`, `excluded_count`, and final source/availability timestamps.
Failure returns an empty owned array, zero output counts and timestamps, false
validity and a reason. `input_count` still describes the supplied array;
`timeframe` is empty until successfully validated. Reasons identify invalid
request fields, future/stale snapshots, invalid row values/timestamps/order,
overlap, missing/insufficient closed history, stale history, or allocation
failure. The bool return must equal `result.valid`.

The harness includes the generated shared fixtures and extra checks for
reusing the result array as input and explicit in-place timeframe normalization.
The generator and Python reference tests are maintained with the fixtures;
those tests execute the existing Python selector and temporal checks, not a
second production Python selector. They do not execute MQL code.

```powershell
py -3.14 -B scripts/generate_native_closed_bar_fixtures.py --check
py -3.14 -B -m pytest tests/python/test_native_closed_bar_fixtures.py tests/python/test_native_observer_source.py
pwsh -NoProfile -File .\scripts\compile_native_observer.ps1
```

Build with `scripts/compile_native_observer.ps1`. It compiles the unchanged EA,
the existing observation harness, and `ClosedBarWindowHarness.mq5` in new
staging (today also the core indicator and risk gate harnesses; PowerShell 7).
The generated fixture include is copied beside its harness and hashed. Each
compile requires a new binary and a log line starting
`Result: 0 errors, 0 warnings,`.
The retained manifest hashes the MQL sources, compiler, script, binaries and
raw logs. Nothing is installed into a terminal directory, and no terminal or
harness is started. The manifest retains the observer scope and lists the
closed-bar scope separately.

Assertions to verify later in an authorized native runtime include boundary
closure, future/forming exclusion, millisecond versus second-resolution ages,
calendar upper bounds, duplicate/descending/overlapping timestamps, preserved
gaps, nonfinite/invalid OHLC/volume/spread, minimum history, full reset after a
prior success, and immutable values. Actual allocation failure still needs a
controlled runtime fault test; its rejection branch has not been forced.

Clean compilation, Python reference cases and source guards are separate
evidence. None certifies MQL assertion execution, complete Python/native parity,
broker data quality, strategy profitability or trading readiness.

Recorded verification on 2026-10-05:

- 64 synthetic shared fixture cases. The generated include contains 1,095
  assertion call sites; the handwritten harness adds eight, for 1,103 total.
  These are source counts, not assertions executed or passed at runtime.
- 130 Python tests passed: 108 fixture/reference/source tests and 22 existing
  native source guards. The fixture owner ran the combined test command above.
- MetaEditor 5.0.0.5833 compiled all three targets with zero errors and zero
  warnings. Newly created binaries remain in isolated temporary staging.
- Source, generated-include and build-script hashes were compared with the
  final manifest before preserving evidence. The copied raw logs were verified
  against their manifest hashes. No terminal or MQL harness was run.

The [compile manifest](evidence/native-closed-bars-2026-10-05/compile-manifest.json)
and [evidence notes](evidence/native-closed-bars-2026-10-05/README.md) identify the
final build and preserved raw logs. Sources are frozen for broader integration
testing; this record does not claim the global Python suite was executed here.
