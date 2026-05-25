$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src/python"
py -m agi_style_forex_bot_mt5.cli `
  --mode paper-risk-clearance `
  --sqlite data\sqlite\forward-shadow-stable.sqlite3 `
  --log-dir data\logs\forward-shadow-stable `
  --reports-root data\reports `
  --paper-risk-dir data\reports\paper_risk `
  --output-dir data\reports\paper_risk_review `
  --reason "Manual review after PAPER_DAILY_DRAWDOWN_HALT; resume only with BALANCED_STABLE_MICRO"
