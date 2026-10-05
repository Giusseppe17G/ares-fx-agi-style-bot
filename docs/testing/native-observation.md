# Native observation build and validation

This component is `NATIVE_OBSERVATION_ONLY`. Its trading release remains
`BLOCKED` even when a demo account, valid quote and complete audit are present.
It generates observations and rejection reasons, not strategy signals.

Build without opening or configuring MetaTrader:

```powershell
./scripts/compile_native_observer.ps1
py -3.14 -B -m pytest tests/python/test_native_observer_source.py
```

The build script copies repository MQL sources and the fixture harness to a new
directory under the system temporary directory. An explicitly supplied staging
path must be new and inside that directory or the worktree. MetaEditor runs
hidden. Success requires both logs to contain `0 errors, 0 warnings` and newly
created binaries. A process exit code alone is insufficient; the installed
compiler returned code 1 with successful logs. The manifest records source,
compiler, build-script, binary and raw log SHA256 hashes. Staging is retained;
neither source nor binaries are copied into a terminal's data directories.

The source tests remove comments and string literals before checking forbidden
capabilities, so documentation mentioning an API does not trigger a false
positive. They also enforce owned includes, unconditional release rejection,
unknown-clock defaults, mandatory initial audit, account revalidation each
cycle and local audit verification. These are source guards, not behavioral
execution of MQL.

`tests/mt5/ObservationPolicyHarness.mq5` contains 31 pure fixture assertions for
account modes, invariant release lock, explicit time configuration, stale/future
ticks, metadata, spread, price/volume grids and JSON/UTC formatting. The harness
is compiled but **has not been run**. It contains no account/market acquisition,
file writes or execution calls. This work does not start Strategy Tester, load
the EA, connect an account or send notifications.

Configuration contract for a later authorized observation session:

- Leave `DEMO_ONLY=true` and `LIVE_TRADING_APPROVED=false`; both are unable to
  release execution. The account must still be positively identified as demo.
- Default `UTC_CLOCK_CONFIRMED=false` and unknown offset intentionally cause
  `INIT_FAILED`. Confirmation must describe a checked host clock, not a guess.
- `SERVER_UTC_OFFSET_SECONDS` means broker raw timestamp minus UTC, in whole
  minutes within -14 to +14 hours. No offset is discovered automatically.
- `UTC_OFFSET_VALID_FROM` is inclusive and `UTC_OFFSET_VALID_UNTIL` exclusive,
  both declared as UTC. Use a verified window excluding broker DST transitions.
- The configured spread limit must be positive and at most 25 points; an
  observed zero spread is allowed but does not certify historical costs.
  Tick freshness is at most five
  seconds using the conservative second-resolution age bound. Tighter limits
  are allowed. Polling intervals are 1–60 seconds and do not manufacture ticks.

Audit files use the terminal file sandbox only, beneath
`AGI_STYLE_FOREX_BOT_MT5/native_observation/`, one new JSONL file per session.
Fields include sequence/run/event identity, UTC or explicit null, environment
or explicit null, symbol, reason, native scope and execution-blocked flags.
Valid snapshots retain raw and normalized timestamps separately. Quote source,
clock authenticity, tick-value conversion and historical cost applicability are
not certified. No real account identifiers or server names are read or logged.

Pending runtime validation must cover audit open/write/flush/readback failure,
cap exhaustion, account switching/disconnection, host clock reversal, expiry of
offset evidence and unavailable symbol properties. External Telegram, SQLite
integration, durable OS-level fault testing, native strategy/risk logic and
promotion evidence are explicitly unfinished outside this module's scope.

The design and official API sources are recorded in
[the native observation ADR](../decisions/2026-10-05-native-observation-release-lock.md).
