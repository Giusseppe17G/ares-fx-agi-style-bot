param(
    [string]$ReportsRoot = "data\reports",
    [string]$OutputDir = "data\reports\operator_drill"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "py" }

$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode operator-drill --reports-root $ReportsRoot --output-dir $OutputDir
exit $LASTEXITCODE
