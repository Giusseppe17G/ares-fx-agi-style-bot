[CmdletBinding(PositionalBinding = $false)]
param(
    [int]$RestartDelaySeconds = 15,
    [string]$Symbols = "EURUSD,GBPUSD,USDJPY",
    [int]$CycleSeconds = 30,
    [string]$SqlitePath = "data\sqlite\forward-shadow.sqlite3",
    [string]$LogDir = "data\logs\forward-shadow",
    [string]$Config = "",
    [switch]$Telegram
)

# Restarts the paper-only forward-shadow run after a crash (exit 1) or a lost
# MT5 terminal (exit 3). It stops instead of relaunching when the run stopped on
# request (0), had invalid arguments or configuration (2), latched its paper
# lifecycle (4) or found MT5 quotes failing integrity checks (5): each of those
# needs the operator. stop_forward_shadow.ps1 stops it cooperatively through
# data\runtime\forward-shadow-watchdog.stop; the PID file only lets it wait.
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$watchdogLogDir = Join-Path $repoRoot "data\logs\watchdog"
New-Item -ItemType Directory -Force -Path $watchdogLogDir | Out-Null
$watchdogLog = Join-Path $watchdogLogDir "forward-shadow-watchdog-$(Get-Date -Format yyyyMMdd).log"
$runtimeDir = Join-Path $repoRoot "data\runtime"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$pidFile = Join-Path $runtimeDir "forward-shadow-watchdog.pid"
$stopFile = Join-Path $runtimeDir "forward-shadow-watchdog.stop"

function Write-WatchdogLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] $Message"
    $line | Tee-Object -FilePath $watchdogLog -Append
}

$sqliteParent = Split-Path $SqlitePath -Parent
if (-not $sqliteParent) { $sqliteParent = "." }
New-Item -ItemType Directory -Force -Path $sqliteParent | Out-Null
$sqliteFull = Join-Path (Resolve-Path -LiteralPath $sqliteParent).ProviderPath (Split-Path $SqlitePath -Leaf)

function Get-RunningForwardShadowProcess {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match "agi_style_forex_bot_mt5\.cli" -and
            $_.CommandLine -match "--mode\s+forward-shadow" -and
            ($_.CommandLine.IndexOf($SqlitePath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
             $_.CommandLine.IndexOf($sqliteFull, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        }
}

if (Test-Path -LiteralPath $pidFile) {
    $previous = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    $alive = $null
    if ($previous -match '^\d+$') { $alive = Get-Process -Id ([int]$previous) -ErrorAction SilentlyContinue }
    if ($alive -and $alive.ProcessName -in @("powershell", "pwsh")) {
        throw "Another forward-shadow watchdog is running (PID $previous)."
    }
}
Remove-Item -LiteralPath $stopFile -ErrorAction SilentlyContinue
# Second line: the SQLite this watchdog supervises, so the stop script only
# stops the watchdog of the base it was given.
Set-Content -LiteralPath $pidFile -Value @("$PID", $sqliteFull) -Encoding utf8

$runArgs = @{ Symbols = $Symbols; CycleSeconds = $CycleSeconds; SqlitePath = $SqlitePath; LogDir = $LogDir }
if ($Config) { $runArgs.Config = $Config }
if ($Telegram) { $runArgs.Telegram = $true }

Write-WatchdogLog "Starting forward-shadow watchdog (PID $PID) on $SqlitePath. DEMO_ONLY=True, LIVE_TRADING_APPROVED=False, paper mode only."
try {
    while ($true) {
        if (Test-Path -LiteralPath $stopFile) {
            Write-WatchdogLog "WATCHDOG_STOPPED: stop requested by stop_forward_shadow.ps1."
            break
        }
        $running = @(Get-RunningForwardShadowProcess)
        if ($running.Count -gt 0) {
            Write-WatchdogLog "Existing forward-shadow process detected: $($running[0].ProcessId). Sleeping."
            Start-Sleep -Seconds $RestartDelaySeconds
            continue
        }

        Write-WatchdogLog "WATCHDOG_RESTART: forward-shadow process missing; starting."
        $exitCode = 1
        try {
            & (Join-Path $repoRoot "scripts\run_forward_shadow.ps1") @runArgs
            $exitCode = $LASTEXITCODE
            Write-WatchdogLog "forward-shadow exited with code $exitCode"
        } catch {
            # The run never started (for example a missing .venv): relaunching cannot fix it.
            Write-WatchdogLog "forward-shadow launch failed: $($_.Exception.Message)"
            $exitCode = 2
        }
        if ($exitCode -in @(0, 2, 4, 5)) {
            Write-WatchdogLog "WATCHDOG_STOPPED: exit code $exitCode (0 stopped on request; 2, 4, 5 need the operator, see docs/GUIA_DE_USO.md); not relaunching."
            break
        }

        Write-WatchdogLog "Waiting $RestartDelaySeconds seconds before restart."
        Start-Sleep -Seconds $RestartDelaySeconds
    }
} finally {
    Remove-Item -LiteralPath $pidFile, $stopFile -ErrorAction SilentlyContinue
}
