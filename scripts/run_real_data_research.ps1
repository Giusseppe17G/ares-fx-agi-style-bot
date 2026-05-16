param(
    [string]$Symbols = "EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD",
    [int]$Bars = 50000,
    [string]$OutputRoot = "data\runs",
    [switch]$FailFast
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logDir = Join-Path $repoRoot "data\logs\real-data-research"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "$timestamp-real-data-research.log"

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "py"
}

$env:PYTHONPATH = "src/python"
$arguments = @(
    "-m", "agi_style_forex_bot_mt5.cli",
    "--mode", "real-data-research",
    "--symbols", $Symbols,
    "--bars", "$Bars",
    "--output-root", $OutputRoot
)
if ($FailFast) {
    $arguments += "--fail-fast"
}

Write-Host "Starting real-data research at $(Get-Date -Format o)"
Write-Host "Repo: $repoRoot"
Write-Host "Log: $logFile"

try {
    if ($pythonExe -eq "py") {
        & py @arguments 2>&1 | Tee-Object -FilePath $logFile
    } else {
        & $pythonExe @arguments 2>&1 | Tee-Object -FilePath $logFile
    }
    $exitCode = $LASTEXITCODE
} catch {
    $_ | Out-String | Tee-Object -FilePath $logFile -Append
    $exitCode = 1
}

Write-Host "Finished real-data research at $(Get-Date -Format o) with exit code $exitCode"
exit $exitCode
