param(
    [string]$SqlitePath = "data\sqlite\forward-shadow-stable.sqlite3",
    [string]$ReportsRoot = "data\reports",
    [string]$OutputDir = "data\reports\market_open_checklist",
    [string]$Symbols = "EURUSD,GBPUSD,USDJPY"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "py"
}

$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode market-open-checklist --sqlite $SqlitePath --reports-root $ReportsRoot --output-dir $OutputDir --symbols $Symbols
exit $LASTEXITCODE
