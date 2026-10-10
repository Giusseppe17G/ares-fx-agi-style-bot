# Native pure risk gate

Date: 2026-10-10. Contract: PROJECT_SPEC section 17.12, package `native_risk_gate_v1`.
Touches: risk (native MQL5), verification tooling. Not wired into the Expert;
no strategy, execution or Python production change. Execution stays blocked.

## Context

The native path had observation, a causal closed-bar window and core
indicators, but `src/mt5/Include/Risk/` and `Contracts/RiskContract.mqh` were
empty. PROJECT_SPEC sections 5.2, 9 and 15 define the Risk Gate; the Python
`RiskEngine` (with `PositionSizer` and `PortfolioGuard`) is the reviewed
reference. IMPLEMENTATION_STATUS lists native risk as pending for the complete
Expert envisioned in the specification.

## Decision

`NativeEvaluateRisk(limits, account, snapshot, signal, positions[], state, decision)`
is a pure function in `src/mt5/Include/Risk/NativeRiskGate.mqh`. It reads no
terminal, account, symbol, clock, file or network state; the caller supplies
every input explicitly, including `now_utc_msc`. It reuses the observer's
`MarketSnapshot` struct. A decision is evidence only:
`execution_authorized` and `full_pipeline_verified` are always false and no
request is built.

- Check order and reject codes mirror `RiskEngine.evaluate`: limits, state,
  account (unknown, non-demo, trading disabled, non-positive equity/balance),
  kill switch, symbol allowed/match, signal and snapshot age, market and signal
  geometry with stops level, audit confirmation, spread, daily drawdown (and
  missing reference), floating drawdown (`reference or balance`), consecutive
  losses, cooldown, candidate risk percentage, sizing, per-trade risk, open
  trade count, per-symbol count and open risk. Python's labelling quirk is kept:
  any market/signal failure reports MISSING_SL or MISSING_TP when that level is
  zero. Drawdown values carried by each rejection match Python.
- Market entries only; pending entry types are outside this version.
- Limits are explicit and validated against PROJECT_SPEC section 6 ceilings:
  DEMO_ONLY true, LIVE_TRADING_APPROVED false, risk per trade (0, 0.5], open
  risk (0, 5], open trades 1..10, per-symbol 1..open trades, daily drawdown
  (0, 3], floating drawdown (0, 5], spread (0, 25], signal age 1..30 s,
  snapshot age 1..5 s, consecutive losses >= 1. Invalid limits reject with
  RISK_LIMITS_INVALID before any other check.

### Exact decimal arithmetic

Python sizes with `Decimal(str(value))`. Doubles cannot reproduce that by
naive rounding: `0.06999999999999999` must floor to 0.06, while `0.29` must stay
0.29. The gate therefore works on an exact 1e-8 lattice:

- `NativeRiskLatticeUnits` accepts a value only when it is the double nearest to
  `units/1e8` (values up to 1e6, so one ulp is far below 1e-8 and the shortest
  decimal form is unique). Prices, tick sizes, tick values and volume limits
  use it.
- `NativeRiskFloorUnits` floors any other double. No lattice point can lie
  between a non-lattice double's shortest decimal form and its binary value,
  so two exactly rounded comparisons find the same floor as Decimal.
- Risk per lot is `ticks * tick_value` with integer ticks between grid prices.
  A lattice tick value yields `(ticks*tick_units)/1e8`, the correctly rounded
  value Python's Decimal product converts to, exactly. A non-lattice tick value
  falls back to one binary product that may differ by one ulp; fixtures use a
  predeclared four-ulp budget there and prove the lot cannot move.

### Native-only, stricter policies

Each is labelled in the fixtures with its own scope and documented difference:
SL, TP, bid and ask must be on the tick grid and the 1e-8 lattice; volume limits
on the lattice; NaN or infinite spread, references, requested risk or open-risk
amounts reject; negative loss counts reject (RISK_STATE_INVALID); unsafe limits
report RISK_LIMITS_INVALID where Python's `validate_safety` raises
INTERNAL_ERROR; spread limits above 25 and zero per-symbol or loss limits are
rejected although Python's config accepts them. Open positions are priced from
their own explicit tick metadata or a known risk amount; the gate never looks
up another snapshot.

## Verification

`scripts/generate_native_risk_gate_fixtures.py` builds 113 synthetic cases,
runs the production `RiskEngine` on each and freezes inputs, Python outputs,
the native expectation and source hashes. Comparable expectations copy Python
without adjustment. The harness `tests/mt5/RiskGateHarness.mq5` has 1433 static
assertions (1423 generated, 10 hand-written lattice checks whose literals are
verified against Decimal in Python). It is the fourth stage of
`NativeMathHarness` (v2) and is compiled by `compile_native_observer.ps1`.

The fixtures are executed under the C++ emulation of section 17.13: all 1433
assertions pass, and deliberate mutations (drawdown boundary, exact lattice
product, audit check, grid checks, naive rounding) are detected. That is not
MetaTrader runtime evidence; MetaEditor compilation and a Tester run remain
pending a Windows environment.

## Limits

No broker data, account, real clock or live quote is used. The gate is not
wired into the Expert, does not track state between calls and does not decide
daily references, losses or cooldowns; a future integration must supply those
from audited state. Passing fixtures do not certify paper or broker behaviour,
financial performance or the Strategy Promotion Gate.
