param(
    [string]$LogDir = "data\logs\forward-shadow",
    [string]$SqlitePath = "data\sqlite\forward-shadow.sqlite3",
    [string]$Symbols = "EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD",
    [int]$CycleSeconds = 30,
    [int]$MaxCycles = 0
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
$runLog = Join-Path $LogDir "forward-shadow-$timestamp.log"

Write-Host "[$(Get-Date -Format o)] Starting forward-shadow run"
Write-Host "DEMO_ONLY=True LIVE_TRADING_APPROVED=False execution_attempted=false"
Write-Host "Log file: $runLog"

$env:PYTHONPATH = "src/python"
$argsList = @(
    "-m", "agi_style_forex_bot_mt5.cli",
    "--mode", "forward-shadow",
    "--symbols", $Symbols,
    "--log-dir", $LogDir,
    "--sqlite", $SqlitePath,
    "--cycle-seconds", "$CycleSeconds"
)
if ($MaxCycles -gt 0) {
    $argsList += @("--max-cycles", "$MaxCycles")
}

& $venvPython @argsList 2>&1 | Tee-Object -FilePath $runLog

$exitCode = $LASTEXITCODE
Write-Host "[$(Get-Date -Format o)] forward-shadow finished with exit code $exitCode"
exit $exitCode

