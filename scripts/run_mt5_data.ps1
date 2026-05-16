param(
    [string]$LogDir = "data\logs\mt5-data-ec2",
    [string]$SqlitePath = "data\sqlite\mt5-data-ec2.sqlite3",
    [string]$Symbols = "EURUSD",
    [int]$Bars = 260
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run scripts\windows_setup.ps1 first."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $SqlitePath -Parent) | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runLog = Join-Path $LogDir "run-$timestamp.log"

Write-Host "[$(Get-Date -Format o)] Starting mt5-data run"
Write-Host "Log file: $runLog"

$env:PYTHONPATH = "src/python"

& $venvPython -m agi_style_forex_bot_mt5.cli `
    --mode mt5-data `
    --symbols $Symbols `
    --bars $Bars `
    --log-dir $LogDir `
    --sqlite $SqlitePath 2>&1 | Tee-Object -FilePath $runLog

$exitCode = $LASTEXITCODE
Write-Host "[$(Get-Date -Format o)] mt5-data run finished with exit code $exitCode"
exit $exitCode
