$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src/python"
py -m agi_style_forex_bot_mt5.cli `
  --mode build-paper-risk-profile `
  --base-profile BALANCED_STABLE `
  --risk-audit-dir data\reports\paper_risk `
  --output-dir data\reports\paper_risk
