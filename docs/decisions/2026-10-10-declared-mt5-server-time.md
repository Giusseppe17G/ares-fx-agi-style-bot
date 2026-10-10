# Declared MT5 server clock and operable forward-shadow stops

Date: 2026-10-10. Touches: MT5 read adapter (tick and bar timestamps), paper
lifecycle control flow, observability and operator tooling. No order path:
broker execution stays removed (`2026-10-05-broker-execution-release-lock.md`),
`DEMO_ONLY=True`.

## Context

`2026-10-05-utc-tick-time-evidence.md` stopped inferring a broker clock offset
from a single tick, correctly: an inferred offset cannot tell a future tick from
an old one. Its consequence was not recorded. The MetaTrader5 Python package
returns tick and bar times on the trade server's wall clock. The demo account
this project observed in May 2026 ran that clock at UTC+3 (its runtime file
recorded offset 10800 on every symbol, removed from the repository in d2f79dc).
On such a broker every tick is three hours "in the future", is rejected, and
forward-shadow can never complete a cycle. Before this change that latched the
SQLite on the first cycle; with the skip policy of
`2026-10-10-operational-forward-shadow.md` it skipped forever. Bars carried the
same offset, which would also shift closed-bar selection and sessions.

A review of the skip policy found five more problems: quotes rejected for
integrity reached the lifecycle as "missing quotes" and were skipped; skips sent
no Telegram notice; a real account behind a disconnected terminal was skipped
instead of latched; `--max-cycles 0` exited 3; and `--cycle-seconds 0` busy-looped
while skipping. The operator tooling could kill a run inside a cycle (a
permanent latch), could not stop an in-session watchdog, and the watchdog
relaunched latched runs forever.

## Decision

- **Declared server clock.** `MT5_SERVER_TIME` is an operator declaration taken
  from the broker's documentation: `UTC` (default, unchanged behaviour),
  `NY_CLOSE` (UTC+3 while the United States observes DST, UTC+2 otherwise; the
  US rule in force since 2007), `EET` (the same offsets on European summer-time
  dates, rule in force since 1996) or a fixed `UTC+HH:MM`. Nothing is inferred.
  `NY_CLOSE` and `EET` differ by one hour for a few weeks each spring and
  autumn, so a wrong choice between them shows up then (stale quotes skipped,
  or quotes ahead stopping the run with code 5).
  `utils/mt5_server_time.py` converts at the read boundary only: tick times in
  `normalize_tick_time`, bar times in `normalize_ohlcv_contract`, range queries
  in the data reader and bar times in `export-history`. Every later freshness,
  closed-bar, session and correlation check is unchanged and works in UTC. A
  server time inside a DST gap or overlap (Sunday morning, market closed), or a
  `NY_CLOSE` time before 2007, is rejected. The inferred offset stays a
  diagnostic (`suggested_broker_time_offset_seconds`); `mt5-diagnose` now turns
  it into `server_time_hint`. A wrong declaration fails closed: a UTC broker
  declared `NY_CLOSE` looks hours stale and is rejected, never fresh. The
  2026-10-05 rule stands: no future tick is accepted, and the declared offset is
  the only conversion.
- **Integrity stop.** The connector marks `integrity_failure` on an invalid tick
  timestamp, on a tick further ahead than the freshness window
  (`max_tick_age_seconds`; a smaller lead is PC clock skew and only drops that
  symbol for the cycle) and on invalid prices or metadata. When such rejections
  leave a cycle with no quotes, or an open paper position without its quote, the
  run stops before any mutation: `FORWARD_SHADOW_INTEGRITY_STOP` (CRITICAL,
  Telegram), `exit_reason=MARKET_DATA_INTEGRITY_FAILED`, exit code 5. It does not
  latch: nothing in the book is uncertain, the usual cause is configuration or
  the PC clock, and every restart validates again. The watchdog does not
  relaunch it.
- **Skip notices.** The first `PAPER_CYCLE_SKIPPED` of a streak and every change
  of reason go to Telegram; `PAPER_CYCLE_RESUMED` reports the end of a streak.
  Skips caused by missing quotes carry each symbol's rejection reason. The
  backoff of an unbounded run starts at `max(cycle_seconds, 5 s)`.
- **Real account first.** `validate_account` checks demo before connection, so a
  real account latches even while the terminal reports disconnected.
- **Cooperative stop.** `--mode stop-shadow` records a request in the SQLite;
  the run polls it before each cycle and once a second while waiting, finishes
  the cycle in progress, consumes the request and exits 0
  (`exit_reason=STOP_REQUESTED`), also while MT5 is unavailable. A request dated
  before the process started belongs to an earlier run (for example after
  `-Force`) and is cleared at startup (`FORWARD_SHADOW_STALE_STOP_CLEARED`). The
  first Ctrl+C does the same as a request; a second one aborts. `resume-shadow`
  clears a pending request. `stop_forward_shadow.ps1`
  asks the watchdog to stop through `data\runtime\forward-shadow-watchdog.stop`,
  requests the stop, waits, and kills only with `-Force` after its timeout.
- **Watchdog and scripts.** The watchdog relaunches only after exit 1 or 3; it
  stops after 0 (deliberate stop), 2, 4 and 5, and refuses a second instance.
  `run_forward_shadow.ps1` refuses a second run on the same SQLite, forwards
  `-Config` and `-Telegram`, rejects unknown or positional arguments (`[CmdletBinding(PositionalBinding = $false)]`) and
  no longer lets a Python warning on stderr abort the wrapper in Windows
  PowerShell 5.1.
- **Exit codes.** 2 also covers a configuration that `load_config` rejects and
  an existing instrument snapshot destination; 3 covers `export-history` and
  `build-instrument-registry` without MT5; `forward-shadow --max-cycles 0` is a
  startup preflight and exits 0. Configuration files and the broker symbol map
  are read as `utf-8-sig`, so a BOM no longer hides the first key or breaks the
  map. `paper-state-report` reports `PAPER_LIFECYCLE_HALTED` ahead of the pause
  the latch also sets, and says the SQLite must be replaced.

## Verification

`tests/python/test_mt5_server_time.py` checks the `NY_CLOSE` offset against the
IANA `America/New_York` zone around every DST transition from 2007 to 2040 and
`EET` against `Europe/Athens` from 1996 to 2040,
round trips, gap and overlap rejection, the tick and bar conversions, the
range-query clock, configuration parsing with a BOM and the diagnose hint.
`tests/python/test_forward_shadow_operations.py` runs the real
`ForwardShadowBot` against a fake terminal: future ticks stop without latching
and a corrected restart continues the same book; a one-second lead is skipped
with its reason; server-stamped ticks complete a cycle under `NY_CLOSE` and stop
under `UTC`; the skip notices, the real-account latch, the backoff floor,
stop requests and Ctrl+C. `tests/python/test_cli_operational_exit_codes.py`
covers the exit codes and the script contracts. The three PowerShell scripts
were run with PowerShell 7 on Linux against a fake interpreter and a stubbed
process list: exit-code propagation, argument quoting, rejection of unknown or
positional arguments, the single-instance refusal, watchdog relaunch after 1 and
3 and stop after 4, the watchdog stop file, and the stop script's clean,
timeout and `-Force` paths. They were not run on Windows or Windows PowerShell
5.1.

## Limits

The declaration must match the broker; a broker that changes its server clock
needs a new declaration. If US or EU summer-time rules change,
`us_dst_bounds_utc` or `eu_dst_bounds_utc` must change with them (the tests
against the system time zone database would show it). Paper
evidence only: nothing here says anything about live fills.
