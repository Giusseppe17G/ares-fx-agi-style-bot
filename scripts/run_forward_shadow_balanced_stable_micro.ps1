$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src/python"
# Paper/shadow only. DEMO_ONLY=True and LIVE_TRADING_APPROVED=False remain mandatory.
# Requires paper-risk-clearance after PAPER_DAILY_DRAWDOWN_HALT.
py -m agi_style_forex_bot_mt5.cli `
  --mode forward-shadow `
  --symbols EURUSD,GBPUSD,USDJPY `
  --signal-profile BALANCED_STABLE_MICRO `
  --profile-config data\reports\paper_risk\balanced_stable_micro.ini `
  --stable-gate data\reports\stable_gate\stable_gate_summary.json `
  --paper-risk-clearance data\reports\paper_risk_review\paper_risk_clearance_ledger.json `
  --sqlite data\sqlite\forward-shadow-stable.sqlite3 `
  --log-dir data\logs\forward-shadow-stable `
  --cycle-seconds 30
