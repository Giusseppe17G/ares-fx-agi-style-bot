# Native observation with an unconditional release lock

Status: accepted for the observation module only. Scope: native data validation
and local observability. No trading release, strategy implementation, risk
approval, historical performance or Python/native parity is implied.

The previously empty EA becomes a modular `NATIVE_OBSERVATION_ONLY` observer.
`NativeExecutionGate` always returns `EXECUTION_NOT_RELEASED`. There is no native
request builder, execution adapter, network client, DLL import, Telegram sender
or activation token. Changing `DEMO_ONLY` or `LIVE_TRADING_APPROVED` cannot
release execution or admit a real/contest/unknown account. Connection and the
successfully read account mode are revalidated before each observation. The
observer never reads account login, server, name or balance.

`MarketSnapshot` retains the conceptual fields in PROJECT_SPEC plus the raw
tick millisecond timestamp, normalized UTC millisecond timestamp and UTC receipt
second. It is a separate native observation schema, not a Python replay input.
Metadata is obtained through boolean property-read overloads; missing values,
nonfinite prices, inconsistent spread, invalid volume lattice, tick-grid errors,
stale/future data or invalid offset evidence reject the observation. Rejection
does not generate a trade signal. A valid quote is still execution-blocked.

UTC handling is deliberately explicit. `TimeGMT()` depends on the host's time
configuration and equals simulated server time inside Strategy Tester; this
observer rejects tester/optimization execution. `TimeTradeServer()` is also a
client-side estimate and is not used to infer a broker offset. These behaviors
are described by [TimeGMT](https://www.mql5.com/en/docs/dateandtime/timegmt) and
[TimeTradeServer](https://www.mql5.com/en/docs/dateandtime/timetradeserver).

An operator must declare clock confirmation, a broker timestamp offset and its
UTC validity window. The raw [MqlTick](https://www.mql5.com/en/docs/constants/structures/mqltick)
timestamp is preserved and converted only under that declaration. Neither the
declaration nor a matching local clock authenticates the source. Offset windows
must exclude broker DST changes. Unknown defaults fail initialization. A host
clock reversal halts observation with a null event timestamp rather than
relabeling the previous timestamp as the current instant.

`TimeGMT()` offers seconds, whereas the quote has milliseconds. The code retains
this difference: the receipt instant is an interval covering that second, and
freshness uses its upper endpoint. Quotes beyond that second reject; subsecond
ordering inside it is unverified. The conservative age can reject a quote up to
999 milliseconds sooner than a higher-resolution synchronized clock would.

Local JSONL is mandatory before successful initialization. A session uses its
own fixed sandbox-relative path, UTF-8 bytes, monotonic sequence identities and
no sharing. Writes must be complete, flushed and read back byte-for-byte;
inconsistency, storage error or the 50 MiB cap stops the observer. No audit file
is overwritten, rotated or deleted. `FileFlush` requests disk persistence but
does not prove storage survival after hardware failure. See
[FileOpen](https://www.mql5.com/en/docs/files/fileopen) and
[FileFlush](https://www.mql5.com/en/docs/files/fileflush).

Every native event contains scope, release status and false execution flags.
Before demo verification its environment is null. If UTC is unavailable its
timestamp is null; these are explicit failures, not fabricated safe values.
The native event schema is `native_observation_event_v1`; no compatibility with
the Python event serializer is asserted. A fixed Print message is the final
fallback when the local audit itself cannot be written. External Telegram and
database export remain pending, with no external message sent by this module.

Compilation occurs in new staging through MetaEditor, using its documented
[/compile, /include and /log interface](https://www.metatrader5.com/en/metaeditor/help/beginning/integration_ide).
No binary is installed into a terminal, no terminal starts, and the fixture
harness is compiled only. Runtime account transitions, filesystem fault
injection and native assertion execution require a later separately authorized
offline test environment. Source guards and clean compilation are not runtime
or broker-equivalence evidence.
