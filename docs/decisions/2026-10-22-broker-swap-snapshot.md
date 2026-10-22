# Broker swap terms recorded read-only, never assumed

Date: 2026-10-22. Touches: observability and backtesting inputs (a new
read-only evidence capture and a measurement helper). No strategy, risk,
execution, Expert or MQL5 behaviour changes. Execution stays removed;
`DEMO_ONLY=True` and `LIVE_TRADING_APPROVED=False` are unchanged.

## Context

Financing (swap) costs were assumed. The predeclared daily slow-premia study
charged an assumed 75 bps a year mark-up on gross exposure
(`docs/research/daily-fx-slow-premia-predeclared-v1.md`), the instrument
registry snapshot deliberately carries no swap fields, and the usage guide asked
the operator to copy swap terms by hand. Without a broker record nobody can say
whether 75 bps is conservative or optimistic for the demo broker, or notice when
the broker changes its terms.

## Decision

- New CLI mode `capture-swap-snapshot` with `--broker-symbol-map` and
  `--swap-snapshot-output`
  (`src/python/agi_style_forex_bot_mt5/swap_snapshot_command.py`); the payload
  is built, verified and written by
  `src/python/agi_style_forex_bot_mt5/broker_swap_snapshot.py`.
- Same safety pattern as `build-instrument-registry`, slightly stricter:
  - every argument is checked before `MetaTrader5` is imported: the map must be
    UTF-8 JSON (a BOM is accepted) without duplicate keys and pass the same
    `validate_symbol_map` as the instrument registry; the destination must not
    exist and its parent must; `MT5_SERVER_TIME` must be canonical. Any failure
    exits 2 (`INVALID_ARGUMENTS` or `OUTPUT_EXISTS`);
  - a missing package, `initialize()` not returning exactly `True` (a truthy
    `1`, `"yes"` or `(True,)` is refused too), or `initialize()` raising exits 3
    (`MT5_UNAVAILABLE`) with a fixed message, since terminal text may name
    accounts, servers or paths;
  - only `initialize`, `symbol_info` and `shutdown` are called; `shutdown`
    runs once the terminal was initialised, also after a failure; no account,
    position, order or history function is called and the payload states
    `account_data_read=False`;
  - the package's exported `SYMBOL_SWAP_MODE_*` and `DAY_OF_WEEK_*` constants
    are read statically (`inspect.getattr_static`, no call) and compared with
    the documented values; a disagreement refuses the capture before connecting
    (exit 2, `CAPTURE_REFUSED`), so a mode is never labelled with the wrong
    name. `enum_constants_checked` records whether any constant was compared;
  - the file is published by hard-linking an fsynced temporary file: an
    existing output is never replaced and no directory is created. A write
    failure exits 2 (`OUTPUT_NOT_WRITABLE`) with a fixed message;
  - the payload, the summary and every refusal are sealed by `SafetyEnvelope`
    with the full safety flags.
- Per mapped symbol only these `symbol_info` fields are copied: `swap_long`,
  `swap_short`, `swap_mode` (raw integer and its `ENUM_SYMBOL_SWAP_MODE` name:
  0 `DISABLED`, 1 `POINTS`, 2 `CURRENCY_SYMBOL`, 3 `CURRENCY_MARGIN`,
  4 `CURRENCY_DEPOSIT`, 5 `INTEREST_CURRENT`, 6 `INTEREST_OPEN`,
  7 `REOPEN_CURRENT`, 8 `REOPEN_BID`), `swap_rollover3days` (raw integer and
  its `ENUM_DAY_OF_WEEK` name), `currency_base`, `currency_profit`,
  `currency_margin`, `trade_contract_size`, `point`, `digits` and the current
  `spread` (as `spread_points`). Quotes, volume limits, tick value and anything
  else `symbol_info` returns are ignored. The payload adds `captured_at_utc`,
  the declared `mt5_server_time`, counts and two hashes.
- Fail closed per symbol: `symbol_info` returning `None` or raising, a missing
  field, a non-finite or wrongly typed number (a bool is not a number), a
  non-positive contract size or point, a negative spread, an unknown swap mode,
  a rollover day outside 0..6, currencies that do not spell the canonical pair,
  a point that is not `10**-digits` or a different symbol name make that symbol
  `UNAVAILABLE` with a closed reason code (never the client's text). The other
  symbols are still captured. Status: `CAPTURED` when all were captured,
  `PARTIAL` when any is unavailable and at least one was captured, and
  `UNAVAILABLE` when none was. The last is a refinement of `PARTIAL`: a
  consumer that requires `CAPTURED` treats both as incomplete. Both are still
  written, because they are evidence of what the broker reported, and the
  summary lists every unavailable symbol and reason. A `PARTIAL` capture exits
  0; an `UNAVAILABLE` one exits 3, like MT5 being unavailable, so a scheduled
  capture whose map matches nothing on the logged-in server never looks
  successful to a caller that checks only the exit code.
- Hashes: `payload_sha256` is the sha256 of the canonical JSON (sorted keys,
  ASCII, compact separators, no NaN) of every other payload field.
  `swap_terms_hash` covers only the schema version and the captured records,
  each without its `status` and `spread_points`: unavailable records, and so
  their reasons, are left out. For the same set of captured symbols it
  therefore changes only when the broker's terms change, never with the capture
  time, the server-time declaration, the spread or a symbol failing for a
  different reason. If a symbol is captured in one snapshot and not in the
  other the hash differs because the covered set differs, so such snapshots are
  compared record by record. `read_swap_snapshot` and `verify_swap_snapshot`
  rebuild every record and both hashes and reject any changed value, changed
  type, added or missing field, unknown reason code or duplicate JSON key. The
  hashes prove integrity, not authentic origin.
- `annualised_swap_carry(record, price=...)` converts `SWAP_MODE_POINTS` terms
  into an approximate annual percent of notional. One rollover on one lot is
  `swap_points * point * contract_size` in the quote currency, valued in USD
  with `derive_tick_value` (tick size = point): directly for USD-quoted pairs,
  through the caller's price of the pair for USD-base pairs. Notional is one
  lot at that price in USD, and a week holds five rollovers, one of them
  triple, so the daily amount accrues 365 times a year. For both kinds of pair
  the rate reduces to `swap_points * point / price * 365`.
  `implied_symmetric_markup_bps_per_year` is `-(long% + short%) / 2` in basis
  points: the broker's mark-up if applied equally around the interest
  differential, the quantity the daily study assumed at 75. The result is
  labelled `carry_status=OBSERVED` and `carry_assumed=False` (measured from the
  broker's terms, no rate or mark-up assumed). `OBSERVED` covers the broker's
  swap terms, not the caller's price: the result also states
  `observed_scope=BROKER_SWAP_TERMS`, `price_source=caller` and
  `price_observed=False`.
  Every other mode, a cross without a USD leg, a triple-swap day on a weekend,
  an invalid price and a record that is not an intact captured record raise
  `InstrumentError` with a reason code. Because the price is the caller's, it
  is checked for plausibility instead of trusted:
  - `price / point` must lie in `[10**4, 10**7)` (`MIN_PRICE_POINTS`,
    `MAX_PRICE_POINTS`), i.e. the price must have five to seven significant
    figures at the symbol's digits, as FX quotes do (EURUSD 1.10 at 5 digits is
    110,000 points, USDJPY 150 at 3 digits is 150,000). A price typed for
    another pair, such as USDJPY at 1.08 (1,080 points, which would report
    about 507% a year for a 15-point swap) or EURUSD at 150 (15,000,000
    points), is refused with `PRICE_SCALE_IMPLAUSIBLE`;
  - a long or short annual carry above 50% of notional in magnitude
    (`MAX_ABS_ANNUAL_CARRY_PERCENT`) is refused with
    `ANNUAL_CARRY_IMPLAUSIBLE`. Interest differentials of USD pairs stay far
    below that outside hyperinflation currencies, so such a figure is far more
    likely a wrong price or a corrupt term than a real swap. A real exotic
    swap above it is refused too; its raw terms remain in the snapshot.

  `snapshot_carry` applies the helper to a verified snapshot and reports each
  refused symbol as `UNAVAILABLE` with its reason; nothing is estimated.
- The instrument registry is untouched in format and hashes. Only its symbol-map
  validation moved into `validate_symbol_map` in
  `src/python/agi_style_forex_bot_mt5/instrument_registry_builder.py` (same
  checks, order and messages) so both captures accept the same maps; a test pins
  the registry hashes computed at d6c8fe4.

## Why per-symbol failure here

The instrument registry feeds sizing and parity checks, so one bad symbol
rejects the whole snapshot. The swap snapshot is a measurement log: discarding
the good symbols because one is missing would only lose evidence, while the bad
symbol is still never estimated.

## Limits

- Nothing reads the snapshot yet: backtests, cost models, the promotion gate and
  paper decisions keep their current inputs. Any future use needs its own
  decision and may only make costs more conservative (for example, the worse of
  the assumed and the observed mark-up).
- The spread is one instantaneous value, not a spread model.
- No price is captured (only instrument fields), so carry needs the caller's
  price. Holiday rollovers, term changes within the year and price drift are
  ignored by the annualisation.
- Money modes need conversion rates and interest or reopen modes need their own
  formulas; they are recorded but not converted. A mode number outside the
  table (from a later terminal build) is recorded `UNAVAILABLE` with
  `SWAP_MODE_UNKNOWN` until the table and its test are extended.
- A snapshot is a point in time; brokers can change swaps at any rollover. The
  guide suggests a weekly capture and comparing `swap_terms_hash` between
  snapshots that captured the same symbols.
- The price checks catch a price on the wrong scale and absurd results, not a
  plausible but stale or slightly wrong price: that error passes through to
  the percentages in proportion.

## Verification

`tests/python/test_broker_swap_snapshot.py` uses a fake terminal that fails the
test on any capability other than `initialize`, `symbol_info` and `shutdown`.
It covers the whitelisted fields, every swap mode and day name, each per-symbol
reason, partial and empty snapshots, map and time validation before any client
call, the enum-constant check, hash reproducibility, both hash definitions
recomputed independently and the terms-hash semantics (unchanged by status or
reason), the closed reason-code whitelist on its own (hashes recomputed),
exclusive and sanitized writes, tampering, the command and CLI exit codes (0,
2, 3, including 3 for an `UNAVAILABLE` capture that is still written), a truthy
non-`True` `initialize()` result, the carry formula for USD-quoted and USD-base
pairs, every refused carry case including implausible price scales and the
annual bound, and the unchanged instrument registry hashes. Each new check was
also confirmed by mutation: disabling it makes at least one test fail.
