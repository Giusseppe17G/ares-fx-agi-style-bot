param(
    [string]$SqlitePath = "data\sqlite\forward-shadow-stable.sqlite3",
    [string]$ReportsRoot = "data\reports",
    [string]$OutputDir = "data\reports\operator_drill"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "py" }

$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode dry-run-market-open --sqlite $SqlitePath --reports-root $ReportsRoot --output-dir $OutputDir
exit $LASTEXITCODE
