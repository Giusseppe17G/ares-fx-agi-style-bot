$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src/python"

py -m agi_style_forex_bot_mt5.cli `
  --mode quarantine-telemetry-issues `
  --sqlite data\sqlite\forward-shadow-stable.sqlite3 `
  --log-dir data\logs\forward-shadow-stable `
  --reports-root data\reports `
  --output-dir data\reports\telemetry_repair `
  --reason "Historical redacted timestamps reviewed after paper reset"
