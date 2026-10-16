param(
    [string]$SqlitePath = "data\sqlite\forward-shadow.sqlite3",
    [string]$LogDir = "data\logs\forward-shadow"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment not found. Run scripts\windows_setup.ps1 first."
    exit 2
}

$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode status --sqlite $SqlitePath --log-dir $LogDir
exit $LASTEXITCODE

