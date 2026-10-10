# C++ emulation of pure native modules

Date: 2026-10-10. Contract: PROJECT_SPEC section 17.13.
Touches: verification tooling only. No MQL5 source, strategy, risk or execution
behaviour changes. Execution stays blocked.

## Context

Native assertions had only been compiled by MetaEditor; none had been
executed. MetaTrader is unavailable in the Linux development environment and
its downloads are blocked there, so the closed-bar window, core indicators and
risk gate fixtures could only run after an authorized Windows Tester run.

## Decision

`scripts/run_native_cpp_emulation.py` translates the pure harnesses and their
whole include graph into C++ and runs them with g++. The translation is
deliberately narrow:

- Only MQL5 array syntax changes: `T &name[]` parameters and `T name[]` /
  `T name[N]` declarations become an `MqlArray<T>` wrapper with bounds-checked
  access; `#property` lines are dropped. Every other line compiles as written.
- A small shim defines `string`, `datetime`, `ArraySize`, `ArrayResize`,
  `ArrayFree`, `MathIsValidNumber`, `MathAbs`, `MathRound`, `MathFloor`,
  `MathSqrt`, `MathExp`, `MathMin`, `MathMax`, `StringLen`, `StringTrimLeft`,
  `StringTrimRight`, `Print` and `PrintFormat`.
- Terminal, account, symbol, clock, file, network and trading APIs are never
  shimmed: a source using one is refused, so only pure modules run. The
  observer harness (account constants, `D''` literals, file audit) is excluded.
- Flags: `-std=c++17 -O0 -ffp-contract=off -fno-fast-math
  -fsanitize=undefined -fno-sanitize-recover=undefined -Wall`. No FMA
  contraction or fast-math reassociation can change binary64 results;
  undefined behaviour aborts the run.
- A suite passes only with its exact reviewed assertion count, zero failures,
  exit code 0, no UBSan report and a single summary record. Evidence records
  the compiler, flags and source hashes and always sets
  `mql5_runtime_verified=false`.

`tests/python/test_native_cpp_emulation.py` runs all suites (skipped when g++
is missing) and runs the risk gate against mutated copies (`--source-root`) to
prove failures are detected.

## Result

closed_bars 1103/1103, core_indicators 1348/1348 and risk_gate 1433/1433
assertions pass with zero compiler warnings and no UBSan report (g++ 13.3.0).
Mutations of the drawdown boundary, the exact lattice product, the audit
check, the tick-grid checks and the lot floor are detected.

## Limits

This is an emulation of MQL5 semantics on IEEE-754 binary64 with an explicit
shim, not MetaTrader runtime evidence. It does not verify the MQL5 compiler,
its string and dynamic-array implementation, `MathRound` tie handling beyond
the tested values, the Strategy Tester, broker data, real clocks, allocation
failure or execution. The MetaEditor compile and Tester run of
`NativeMathHarness` remain the authoritative native verification.
