# MT5 Time Normalization

Phase 28 adds broker/server timestamp normalization for MT5 data-only reads.

Some brokers expose `tick.time` or `tick.time_msc` in server time rather than true UTC. A fresh tick can therefore look several hours in the future on a local Windows PC or on AWS EC2. The bot now detects known broker offsets dynamically and normalizes the tick timestamp before freshness checks.

## What Is Normalized

The normalizer reads:

- `tick.time_msc` when available.
- `tick.time` as fallback.
- the current Python UTC clock.

It reports:

- `tick_time_utc_raw`
- `normalized_tick_utc`
- `timestamp_normalized`
- `broker_time_offset_seconds`
- `tick_age_seconds_raw`
- `tick_age_seconds_normalized`
- `tick_time_status`
- `normalization_reason`

Known offsets are configurable and default to:

```text
-10800,-7200,-3600,0,3600,7200,10800
```

The local Windows timezone is audited only. It is never used as a trading-time source.

## Fail-Closed Rules

Ticks remain rejected when:

- timestamp parsing fails.
- bid/ask/point are invalid.
- the future timestamp is beyond `MAX_FUTURE_TICK_OFFSET_SECONDS`.
- the future offset does not match a known broker offset.
- the normalized timestamp is still stale.
- rates are empty or symbol metadata is invalid.

Normalization does not enable demo or live execution.

## Local Validation

```powershell
Get-Date
(Get-Date).ToUniversalTime()
Get-TimeZone

$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --symbols EURUSD,GBPUSD,USDJPY --log-dir data\logs\mt5-diagnose-open --sqlite data\sqlite\mt5-diagnose-open.sqlite3
```

Expected for a broker server at UTC+3:

```json
{
  "timestamp_normalized": true,
  "broker_time_offset_seconds": 10800,
  "tick_time_status": "NORMALIZED_FRESH",
  "symbols_rejected": 0,
  "execution_attempted": false
}
```

## Forward-Shadow Smoke

```powershell
py -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY --signal-profile BALANCED_STABLE --profile-config data\reports\stability_repair\balanced_stable.ini --stable-gate data\reports\stable_gate\stable_gate_summary.json --sqlite data\sqlite\forward-shadow-stable-smoke.sqlite3 --log-dir data\logs\forward-shadow-stable-smoke --cycle-seconds 0 --max-cycles 1
```

Forward-shadow remains paper/shadow only. It audits `TICK_TIME_NORMALIZED` or `STABLE_TICK_TIME_NORMALIZED` when a broker offset is applied.
