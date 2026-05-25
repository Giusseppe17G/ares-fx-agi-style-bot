$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src/python"

py -m agi_style_forex_bot_mt5.cli `
  --mode paper-pnl-audit `
  --sqlite data\sqlite\forward-shadow-stable.sqlite3 `
  --log-dir data\logs\forward-shadow-stable `
  --reports-root data\reports `
  --paper-risk-dir data\reports\paper_risk `
  --daily-risk-dir data\reports\paper_daily_risk `
  --profile-config data\reports\paper_risk\balanced_stable_micro.ini `
  --output-dir data\reports\paper_pnl_audit
