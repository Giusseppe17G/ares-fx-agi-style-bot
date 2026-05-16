param(
    [string]$LogDir = "data\logs\mt5-diagnose-ec2",
    [string]$SqlitePath = "data\sqlite\mt5-diagnose-ec2.sqlite3"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at $venvPython. Run scripts\windows_setup.ps1 first."
    exit 2
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $SqlitePath -Parent) | Out-Null

$env:PYTHONPATH = "src/python"
$timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
Write-Host "[$timestamp] Preparing MT5 diagnose mode from $repoRoot"

$helpOutput = & $venvPython -m agi_style_forex_bot_mt5.cli --help 2>&1 | Out-String
if ($helpOutput -notmatch "mt5-diagnose") {
    Write-Host "mt5-diagnose mode depends on Fase 3B and is not implemented in the current CLI."
    Write-Host "Current safe diagnostic path: run scripts\run_mt5_data.ps1 and review JSONL/SQLite output."
    Write-Host "Future command prepared by this script:"
    Write-Host ".\.venv\Scripts\python.exe -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --log-dir $LogDir --sqlite $SqlitePath"
    exit 2
}

& $venvPython -m agi_style_forex_bot_mt5.cli --mode mt5-diagnose --log-dir $LogDir --sqlite $SqlitePath
exit $LASTEXITCODE
