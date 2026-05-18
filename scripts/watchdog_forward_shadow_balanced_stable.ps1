param(
    [int]$RestartDelaySeconds = 15,
    [string]$Symbols = "EURUSD,GBPUSD,USDJPY",
    [string]$ProfileConfig = "data\reports\stability_repair\balanced_stable.ini",
    [string]$StableGate = "data\reports\stable_gate\stable_gate_summary.json",
    [int]$CycleSeconds = 30
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$watchdogLogDir = Join-Path $repoRoot "data\logs\watchdog"
New-Item -ItemType Directory -Force -Path $watchdogLogDir | Out-Null
$watchdogLog = Join-Path $watchdogLogDir "forward-shadow-balanced-stable-watchdog-$(Get-Date -Format yyyyMMdd).log"

function Write-WatchdogLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] $Message"
    $line | Tee-Object -FilePath $watchdogLog -Append
}

function Get-RunningForwardShadowStableProcess {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match "agi_style_forex_bot_mt5\.cli" -and
            $_.CommandLine -match "--mode\s+forward-shadow" -and
            $_.CommandLine -match "--signal-profile\s+BALANCED_STABLE"
        }
}

Write-WatchdogLog "Starting BALANCED_STABLE forward-shadow watchdog. DEMO_ONLY=True, LIVE_TRADING_APPROVED=False, paper mode only."

while ($true) {
    $running = @(Get-RunningForwardShadowStableProcess)
    if ($running.Count -gt 0) {
        Write-WatchdogLog "Existing BALANCED_STABLE forward-shadow process detected: $($running[0].ProcessId). Sleeping."
        Start-Sleep -Seconds $RestartDelaySeconds
        continue
    }

    Write-WatchdogLog "WATCHDOG_RESTART: BALANCED_STABLE forward-shadow process missing; starting."
    try {
        & (Join-Path $repoRoot "scripts\run_forward_shadow_balanced_stable.ps1") -Symbols $Symbols -ProfileConfig $ProfileConfig -StableGate $StableGate -CycleSeconds $CycleSeconds
        $exitCode = $LASTEXITCODE
        Write-WatchdogLog "BALANCED_STABLE forward-shadow exited with code $exitCode"
    } catch {
        Write-WatchdogLog "BALANCED_STABLE forward-shadow launch failed: $($_.Exception.Message)"
    }

    Write-WatchdogLog "Waiting $RestartDelaySeconds seconds before restart."
    Start-Sleep -Seconds $RestartDelaySeconds
}
