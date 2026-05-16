# Persistence And Recovery

Phase 13 hardens persistence for 24/7 `forward-shadow` operation.

It does not enable demo/live execution and never calls `order_send`.

Safety invariants:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`

## Components

- Canonical `AuditEvent` with optional hash chaining.
- Idempotent SQLite migration runner.
- SQLite health checks using `PRAGMA integrity_check`.
- Local backup manager for SQLite and JSONL logs.
- Audit replay from SQLite telemetry.
- Event integrity checks.
- Telegram outbox retry worker.
- JSONL compactor with backup before rotation.
- Recovery manager called at `forward-shadow` startup.

## Commands

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode db-migrate --sqlite data\sqlite\forward-shadow.sqlite3

py -m agi_style_forex_bot_mt5.cli --mode db-health --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\persistence

py -m agi_style_forex_bot_mt5.cli --mode backup --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow --backup-dir data\backups

py -m agi_style_forex_bot_mt5.cli --mode audit-replay --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\persistence

py -m agi_style_forex_bot_mt5.cli --mode telegram-outbox-flush --sqlite data\sqlite\forward-shadow.sqlite3

py -m agi_style_forex_bot_mt5.cli --mode compact-logs --log-dir data\logs\forward-shadow --backup-dir data\backups
```

## Startup Recovery

`forward-shadow` emits:

- `RECOVERY_STARTED`
- `RECOVERY_COMPLETED`
- `RECOVERY_FAILED` if checks fail

If recovery fails, the bot fails closed before connecting or creating new paper trades.

