# Audit Replay

Audit replay reconstructs paper trading state from durable telemetry.

It reads SQLite and writes:

- `data/reports/persistence/audit_replay_report.json`
- `data/reports/persistence/event_integrity_report.json`
- `data/reports/persistence/report.html`

Replay reconstructs:

- Open and closed paper trades.
- Paper equity curve.
- Alerts.
- Portfolio decision counts.
- Event integrity findings.

Run:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode audit-replay --sqlite data\sqlite\forward-shadow.sqlite3 --report-dir data\reports\persistence
```

Warnings include duplicate idempotency keys, heartbeat gaps, paper trade lifecycle inconsistencies, and recurring Telegram errors.

Replay is diagnostic only. It cannot enable trading.

