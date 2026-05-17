param(
    [string]$LogDir = "data\logs\forward-shadow-stable",
    [string]$SqlitePath = "data\sqlite\forward-shadow-stable.sqlite3",
    [string]$ProfileConfig = "data\reports\stability_repair\balanced_stable.ini",
    [string]$Symbols = "EURUSD,GBPUSD,USDJPY",
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
if (-not (Test-Path $ProfileConfig)) {
    throw "BALANCED_STABLE profile config not found: $ProfileConfig"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $SqlitePath -Parent) | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runLog = Join-Path $LogDir "forward-shadow-balanced-stable-$timestamp.log"

Write-Host "[$(Get-Date -Format o)] Starting BALANCED_STABLE forward-shadow paper run"
Write-Host "DEMO_ONLY=True LIVE_TRADING_APPROVED=False execution_attempted=false order_send=false order_check=false"
Write-Host "Profile config: $ProfileConfig"
Write-Host "Log file: $runLog"

$env:PYTHONPATH = "src/python"
$argsList = @(
    "-m", "agi_style_forex_bot_mt5.cli",
    "--mode", "forward-shadow",
    "--symbols", $Symbols,
    "--log-dir", $LogDir,
    "--sqlite", $SqlitePath,
    "--cycle-seconds", "$CycleSeconds",
    "--signal-profile", "BALANCED_STABLE",
    "--profile-config", $ProfileConfig
)
if ($MaxCycles -gt 0) {
    $argsList += @("--max-cycles", "$MaxCycles")
}

& $venvPython @argsList 2>&1 | Tee-Object -FilePath $runLog

$exitCode = $LASTEXITCODE
Write-Host "[$(Get-Date -Format o)] BALANCED_STABLE forward-shadow finished with exit code $exitCode"
exit $exitCode
