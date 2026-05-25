$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src/python"

py -m agi_style_forex_bot_mt5.cli `
  --mode paper-risk-post-fix-gate `
  --reports-root data\reports `
  --output-dir data\reports\paper_pnl_audit
