param(
    [string]$Symbols = "EURUSD,GBPUSD,USDJPY",
    [string]$SqlitePath = "data\sqlite\forward-shadow-stable.sqlite3",
    [string]$ReportsRoot = "data\reports",
    [string]$LogDir = "data\logs\forward-shadow-stable"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "py" }

$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --symbols $Symbols --log-dir data\logs\mt5-diagnose-open --sqlite data\sqlite\mt5-diagnose-open.sqlite3
& $venvPython -m agi_style_forex_bot_mt5.cli --mode live-feature-contract --symbols $Symbols --output-dir "$ReportsRoot\forward_diagnostics"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode resume-shadow --sqlite $SqlitePath --reason "EC2 market open paper-only resume after diagnostics"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode forward-shadow --symbols $Symbols --signal-profile BALANCED_STABLE --profile-config "$ReportsRoot\stability_repair\balanced_stable.ini" --stable-gate "$ReportsRoot\stable_gate\stable_gate_summary.json" --sqlite $SqlitePath --log-dir $LogDir --cycle-seconds 30
exit $LASTEXITCODE
