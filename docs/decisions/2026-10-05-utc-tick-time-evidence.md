# UTC tick freshness cannot be inferred from an hour offset

Status: accepted. Scope: Python market-data validation and paper lifecycle.

The [official MT5 Python documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksfrom_py)
states that terminal tick and bar times are UTC. No verified source in this
project establishes another timestamp basis for a Python input stream.

The former normalizer inferred an offset from a single future-looking tick,
subtracted that offset, and accepted the resulting timestamp as fresh. This
cannot distinguish a raw timestamp one hour ahead from a source with a true
two-hour offset whose quote is one hour old. Both raw values become `now +
3600`, and both previously returned `NORMALIZED_FRESH` with age zero. A correctly
encoded UTC tick one hour old was already rejected; that behavior is preserved.

Only raw selected UTC epochs with age in `[0, max_tick_age_seconds]` are now
fresh. Every future timestamp is rejected, including a positive millisecond
within the freshness allowance. Inferred hour offsets remain diagnostic hints
in `suggested_broker_time_offset_seconds`; their provenance is explicitly
unverified. They never change the selected epoch, set `timestamp_normalized`,
or authorize a paper decision. The secondary classifier follows the same rule.

Function signatures and legacy flags remain accepted. Flags control diagnostic
suggestions, not an authorization path. Previously accepted `NORMALIZED_FRESH`
outputs intentionally become rejections; a suggested offset is identified by
reason `BROKER_TIME_OFFSET_UNVERIFIED`. Applied offset stays zero. The connector
therefore does not automatically write inferred offsets as confirmed runtime
evidence. Existing hint files are not conversion authority.

Native EA server-time conventions cannot be imported into this Python contract.
Supporting a different source clock requires independently verified timestamp
provenance and a separately reviewed adapter; there is no new escape parameter.
This change does not enable broker execution or modify strategy thresholds.

Reproduction: `test_tick_time_provenance.py` had eight failures and four passing
UTC-boundary controls before the fix. It now verifies ambiguous offsets, small
future values, stale ticks, exact accepted boundaries, classifier consistency
and the inability of legacy flags to restore inferred conversion. Existing
phase28 integration tests retain read-only fake clients and now require rejection
with no paper entry and no automatic offset file.
