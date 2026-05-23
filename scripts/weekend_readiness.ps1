param(
    [string]$SqlitePath = "data\sqlite\forward-shadow-stable.sqlite3",
    [string]$LogDir = "data\logs\forward-shadow-stable",
    [string]$ReportsRoot = "data\reports",
    [string]$OutputDir = "data\reports\weekend_readiness"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "py"
}

$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode weekend-readiness --sqlite $SqlitePath --log-dir $LogDir --reports-root $ReportsRoot --output-dir $OutputDir
exit $LASTEXITCODE
