param(
    [int]$RestartDelaySeconds = 15,
    [string]$Symbols = "EURUSD,GBPUSD,USDJPY,USDCAD,USDCHF,AUDUSD,EURJPY,NZDUSD",
    [int]$CycleSeconds = 30
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$watchdogLogDir = Join-Path $repoRoot "data\logs\watchdog"
New-Item -ItemType Directory -Force -Path $watchdogLogDir | Out-Null
$watchdogLog = Join-Path $watchdogLogDir "forward-shadow-watchdog-$(Get-Date -Format yyyyMMdd).log"

function Write-WatchdogLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] $Message"
    $line | Tee-Object -FilePath $watchdogLog -Append
}

function Get-RunningForwardShadowProcess {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match "agi_style_forex_bot_mt5\.cli" -and
            $_.CommandLine -match "--mode\s+forward-shadow"
        }
}

Write-WatchdogLog "Starting forward-shadow watchdog. DEMO_ONLY=True, LIVE_TRADING_APPROVED=False, paper mode only."

while ($true) {
    $running = @(Get-RunningForwardShadowProcess)
    if ($running.Count -gt 0) {
        Write-WatchdogLog "Existing forward-shadow process detected: $($running[0].ProcessId). Sleeping."
        Start-Sleep -Seconds $RestartDelaySeconds
        continue
    }

    Write-WatchdogLog "WATCHDOG_RESTART: forward-shadow process missing; starting."
    try {
        & (Join-Path $repoRoot "scripts\run_forward_shadow.ps1") -Symbols $Symbols -CycleSeconds $CycleSeconds
        $exitCode = $LASTEXITCODE
        Write-WatchdogLog "forward-shadow exited with code $exitCode"
    } catch {
        Write-WatchdogLog "forward-shadow launch failed: $($_.Exception.Message)"
    }

    Write-WatchdogLog "Waiting $RestartDelaySeconds seconds before restart."
    Start-Sleep -Seconds $RestartDelaySeconds
}

