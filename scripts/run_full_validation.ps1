Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$env:PYTHONPATH = "src/python"
$symbols = "EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD"
$started = Get-Date -Format "o"
Write-Host "Starting full-validation at $started"

.\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli `
  --mode full-validation `
  --symbols $symbols `
  --data-dir data\historical `
  --reports-root data\reports `
  --sqlite data\sqlite\forward-shadow.sqlite3 `
  --log-dir data\logs\full-validation `
  --output-dir data\reports\full_validation `
  --skip-export-history

exit $LASTEXITCODE
