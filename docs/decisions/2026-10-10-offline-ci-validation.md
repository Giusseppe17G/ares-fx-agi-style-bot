# Offline CI validation workflow

Date: 2026-10-10. Touches: tooling/observability only. No strategy, risk,
execution, Expert or production Python behaviour changes.

## Context

`PROJECT_SPEC.md` §16 left CI undefined. Every check ran only on a developer
machine, so a clock-dependent test, a stale generated fixture or a broken
document could reach `main` unnoticed.

## Decision

`.github/workflows/validation.yml` runs on every push and pull request:

1. Documentation lint (`scripts/check_docs.py`, see
   `2026-10-10-documentation-lint.md`).
2. `--check` of the three native fixture generators: generated MQL fixtures
   must equal what the current Python references produce.
3. C++ emulation of the pure native modules (`scripts/run_native_cpp_emulation.py`,
   §17.13).
4. The full pytest suite with `-B -p no:cacheprovider`.

The job uses `permissions: contents: read`, checks out without persisting
credentials, and needs no MetaTrader, broker, account, secret or network access
beyond installing packages.

External dependencies (AGENTS.md rule 9):

- `actions/checkout@v4` and `actions/setup-python@v5`: maintained by GitHub,
  MIT licence, the standard way to fetch the repository and a CPython build on
  hosted runners. Pinned to a major version tag. GitHub currently runs both on
  Node.js 24 with a deprecation notice for Node.js 20; moving to the next major
  versions is a maintenance item, not a behaviour change.
- Python 3.14.4, NumPy 2.4.4, pandas 3.0.2, requests 2.34.2 and pytest 9.1.1,
  pinned exactly. 3.14.4 is the reference runtime of the frozen native
  indicator fixtures, and exact pins keep generator `--check` and float-
  sensitive tests reproducible. Pins change only with a reviewed update that
  regenerates fixtures with `--check` passing.
- `g++` and `git` from the hosted Ubuntu 24.04 image; nothing else is installed.

## Limits

CI does not compile MQL5 or start MetaTrader: MetaEditor compilation and the
Strategy Tester run (§17.11) still require an authorized Windows run. A green CI
says nothing about profitability, broker behaviour or the Strategy Promotion Gate.
