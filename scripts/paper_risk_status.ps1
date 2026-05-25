$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src/python"
py -m agi_style_forex_bot_mt5.cli `
  --mode paper-risk-status `
  --sqlite data\sqlite\forward-shadow-stable.sqlite3 `
  --profile-config data\reports\paper_risk\balanced_stable_micro.ini `
  --output-dir data\reports\paper_risk
