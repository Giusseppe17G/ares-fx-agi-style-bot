# Windows EC2 24/7 Deployment

This guide prepares an AWS EC2 Windows instance to run `AGI_STYLE_FOREX_BOT_MT5` in safe MT5 data-only/shadow mode.

Target environment for this phase:

- AWS EC2 Windows Server 2025.
- Instance type `t3.micro`.
- RDP access enabled.
- MetaTrader 5 running in the desktop session.

`t3.micro` is intentionally small. Keep the symbol list modest, avoid extra charts/tools in MT5, and use `scripts\healthcheck.ps1` to watch disk and memory pressure.

## Safety Status

Required safety defaults remain:

- `DEMO_ONLY=True`
- `LIVE_TRADING_APPROVED=False`
- `execution_attempted=false`
- `order_send was not called`

This deployment guide does not enable real trading, demo order execution, or live broker order execution.

## 1. Connect By RDP

1. Open the AWS EC2 console.
2. Select the Windows instance.
3. Choose **Connect** -> **RDP client**.
4. Download the RDP file or copy the public DNS/IP.
5. Decrypt the Administrator password with your EC2 key pair.
6. Connect with Microsoft Remote Desktop.

Do not commit `.rdp`, `.pem`, `.key`, passwords, MT5 credentials, Telegram tokens, AWS credentials, or GitHub tokens to the repository.

## 2. Install Git

Download and install Git for Windows:

```powershell
winget install --id Git.Git -e
```

If `winget` is unavailable, install Git from the official Git for Windows installer.

Verify:

```powershell
git --version
```

## 3. Install Python 3.11+

Install Python:

```powershell
winget install --id Python.Python.3.11 -e
```

Verify:

```powershell
py -3 --version
```

## 4. Install MetaTrader 5

1. Download MetaTrader 5 from your broker or MetaQuotes.
2. Install MT5 on the EC2 Windows desktop.
3. Launch MT5 at least once over RDP.
4. Log into a demo account.
5. Keep the terminal running as `terminal64.exe`.
6. Ensure the required symbols are visible in Market Watch.

For `mt5-data`, a real account is read-only if detected, but the safer deployment target is a demo terminal. Under `DEMO_ONLY=True`, a real account triggers `ACCOUNT_REAL_DETECTED_READ_ONLY` and the bot stops before symbol processing.

## 5. Clone The Repository

```powershell
cd C:\Users\Administrator
git clone https://github.com/Giusseppe17G/ares-fx-agi-style-bot.git
cd ares-fx-agi-style-bot
```

If using a private repository, authenticate with GitHub using a local credential manager or token outside the repo.

## 6. Create Local Environment

Run:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\windows_setup.ps1
```

The setup script:

- Verifies Python 3.11+.
- Creates `.venv`.
- Upgrades pip.
- Installs dependencies with `py -m pip install -e ".[dev,mt5]"`.
- Verifies `import MetaTrader5`.
- Creates `data\logs`, `data\sqlite`, and `data\reports`.
- Does not ask for or store secrets.

## 7. Configure Local `.env`

Create `.env` locally if you need Telegram or local overrides. Do not commit it.

Example:

```powershell
@"
TELEGRAM_BOT_TOKEN=replace_locally
TELEGRAM_CHAT_ID=replace_locally
"@ | Set-Content -Encoding UTF8 .env
```

The current scripts do not require `.env` for safe operation. If you load `.env` later, keep it local only.

## 8. Run MT5 Data-Only Smoke

PowerShell:

```powershell
$env:PYTHONPATH="src/python"
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode mt5-data --log-dir data\logs\mt5-data-smoke --sqlite data\sqlite\mt5-data-smoke.sqlite3
```

Or use the script:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\run_mt5_data.ps1
```

Expected safety fields in output:

```json
{
  "mode": "mt5-data",
  "execution_attempted": false
}
```

Confirm:

- `execution_attempted=false`
- `order_send was not called`
- any created order is a `ShadowOrder` with `mode=shadow` and `status=created`

## 9. Review SQLite

SQLite path:

```text
data\sqlite\mt5-data-ec2.sqlite3
```

Inspect tables with a SQLite viewer or CLI:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/sqlite/mt5-data-ec2.sqlite3'); print(c.execute('select name from sqlite_master where type=''table''').fetchall())"
```

Important tables:

- `events`
- `orders`
- `telegram_outbox`
- `delivery_attempts`

The `orders` table must contain shadow orders only.

## 10. Review JSONL

JSONL path:

```text
data\logs\mt5-data-ec2
```

Read latest log:

```powershell
Get-ChildItem data\logs\mt5-data-ec2 -Filter *.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content -Tail 20
```

Look for:

- `BOT_STARTED`
- `MT5_CONNECTED` or `MT5_CONNECTION_FAILED`
- `ACCOUNT_SNAPSHOT`
- `SIGNAL_DETECTED`
- `SIGNAL_REJECTED`
- `RISK_REJECTED`
- `SHADOW_ORDER_CREATED`
- `BOT_STOPPED`

There should be no `ORDER_SENT` from `mt5-data`.

## 11. Review Telegram

Telegram is optional.

If enabled in a future wrapper, notifications should be fail-safe:

- failures are logged as `TELEGRAM_ERROR`
- secrets are redacted
- the bot loop continues
- failed messages are durable only when SQLite is supplied

## 12. Task Scheduler 24/7 Watchdog

Create a Windows Task Scheduler task:

1. Open **Task Scheduler**.
2. Choose **Create Task**.
3. General:
   - Name: `AGI_STYLE_FOREX_BOT_MT5 mt5-data watchdog`
   - Select **Run only when user is logged on** if MT5 requires desktop session.
   - Select **Run with highest privileges** if required by local policy.
4. Triggers:
   - New trigger: **At log on**.
5. Actions:
   - Program/script: `powershell.exe`
   - Arguments:

```text
-ExecutionPolicy Bypass -File C:\ruta\del\repo\scripts\watchdog_mt5_data.ps1
```

   - Start in:

```text
C:\ruta\del\repo
```

6. Settings:
   - Enable **Restart every** if task fails.
   - Enable task history for diagnostics.

Watchdog logs:

```text
data\logs\watchdog
```

## 13. Healthcheck

Run:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\healthcheck.ps1
```

The healthcheck reports:

- MT5 terminal process.
- Python bot process.
- Latest JSONL.
- Whether latest event is `CRITICAL_ERROR`.
- SQLite file existence.
- Free disk space.
- Approximate free memory.

Exit codes:

- `0`: OK.
- `1`: WARNING.
- `2`: CRITICAL.

## 14. Forward Shadow 24/7

After `mt5-data` and `mt5-diagnose` are healthy, run paper lifecycle observation:

```powershell
$env:PYTHONPATH="src/python"
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD --log-dir data\logs\forward-shadow --sqlite data\sqlite\forward-shadow.sqlite3 --cycle-seconds 30
```

Smoke test:

```powershell
$env:PYTHONPATH="src/python"
.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols EURUSD --log-dir data\logs\forward-shadow-smoke --sqlite data\sqlite\forward-shadow-smoke.sqlite3 --cycle-seconds 0 --max-cycles 1
```

Expected output includes:

```json
{
  "mode": "forward-shadow",
  "execution_attempted": false
}
```

Forward shadow manages paper trades only. It must not create demo or live broker orders, and `order_send was not called` must remain true.

## 15. MT5 Diagnose Mode

Use this when `mt5-data` rejects symbols because the tick is stale or symbol mapping is unclear:

```powershell
.\scripts\run_mt5_diagnose.ps1
```

The script runs `--mode mt5-diagnose`, audits `MT5_DIAGNOSTIC`, prints `tick.time`, `tick.time_msc`, UTC interpretations, tick age, broker symbol mapping, `market_is_probably_closed`, and MT5 `last_error()`. It does not generate signals, create shadow orders, or call `order_send`.

If `reject_code=MARKET_CLOSED_OR_NO_TICKS`, verify MT5 is connected, the symbol is visible in Market Watch, and the Forex session is open. A weekend or no fresh broker ticks should remain rejected; do not increase `MAX_TICK_AGE_SECONDS` just to bypass this.

## 16. Operational Checklist

Before leaving EC2 unattended:

- MT5 terminal is open and logged into demo.
- `py -m pytest -q` passes locally.
- `scripts\run_mt5_data.ps1` returns JSON with `execution_attempted=false`.
- `forward-shadow` smoke returns JSON with `execution_attempted=false`.
- JSONL logs are being written.
- SQLite file is being updated.
- Paper trades, if any, are stored in `paper_trades`.
- Watchdog task is enabled.
- Disk free space is healthy.
- No secrets are present in git status.
- `DEMO_ONLY=True`.
- `LIVE_TRADING_APPROVED=False`.
- `order_send was not called`.
