$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src/python"

py -m agi_style_forex_bot_mt5.cli `
  --mode paper-daily-risk-clear `
  --sqlite data\sqlite\forward-shadow-stable.sqlite3 `
  --log-dir data\logs\forward-shadow-stable `
  --reports-root data\reports `
  --paper-risk-dir data\reports\paper_risk `
  --clearance-ledger data\reports\paper_risk_review\paper_risk_clearance_ledger.json `
  --profile-config data\reports\paper_risk\balanced_stable_micro.ini `
  --output-dir data\reports\paper_daily_risk `
  --reason "Clear stale paper drawdown halt after manual review and micro clearance"
