# Backup And Restore

Backups are local, explicit, and secret-safe.

The backup command copies:

- SQLite telemetry database.
- Recent JSONL audit files.

It does not copy `.env`, credentials, RDP files, private keys, or tokens.

Run:

```powershell
$env:PYTHONPATH="src/python"
py -m agi_style_forex_bot_mt5.cli --mode backup --sqlite data\sqlite\forward-shadow.sqlite3 --log-dir data\logs\forward-shadow --backup-dir data\backups
```

Recommended operating rhythm:

- Run backup before migrations.
- Run backup before log compaction.
- Keep backups outside Git.
- Verify `db-health` after restoring a database.

Restore is manual for now: stop the bot, copy the selected `.sqlite3` backup back to `data\sqlite\forward-shadow.sqlite3`, then run `db-health` and `audit-replay`.

