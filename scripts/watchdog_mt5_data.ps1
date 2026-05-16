param(
    [int]$RestartDelaySeconds = 10,
    [string]$Symbols = "EURUSD",
    [int]$Bars = 260
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$watchdogLogDir = Join-Path $repoRoot "data\logs\watchdog"
New-Item -ItemType Directory -Force -Path $watchdogLogDir | Out-Null
$watchdogLog = Join-Path $watchdogLogDir "watchdog-$(Get-Date -Format yyyyMMdd).log"

function Write-WatchdogLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] $Message"
    $line | Tee-Object -FilePath $watchdogLog -Append
}

function Get-RunningMt5DataProcess {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match "agi_style_forex_bot_mt5\.cli" -and
            $_.CommandLine -match "--mode\s+mt5-data"
        }
}

Write-WatchdogLog "Starting mt5-data watchdog. DEMO_ONLY=True, LIVE_TRADING_APPROVED=False, read-only mode."
Write-WatchdogLog "For 24/7 paper lifecycle use scripts\watchdog_forward_shadow.ps1 after mt5-data smoke is healthy."

while ($true) {
    $running = @(Get-RunningMt5DataProcess)
    if ($running.Count -gt 0) {
        Write-WatchdogLog "Existing mt5-data process detected: $($running[0].ProcessId). Sleeping."
        Start-Sleep -Seconds $RestartDelaySeconds
        continue
    }

    Write-WatchdogLog "No mt5-data process detected. Starting one-shot mt5-data run."
    try {
        & (Join-Path $repoRoot "scripts\run_mt5_data.ps1") -Symbols $Symbols -Bars $Bars
        $exitCode = $LASTEXITCODE
        Write-WatchdogLog "mt5-data process exited with code $exitCode"
    } catch {
        Write-WatchdogLog "mt5-data launch failed: $($_.Exception.Message)"
    }

    Write-WatchdogLog "Waiting $RestartDelaySeconds seconds before restart."
    Start-Sleep -Seconds $RestartDelaySeconds
}
