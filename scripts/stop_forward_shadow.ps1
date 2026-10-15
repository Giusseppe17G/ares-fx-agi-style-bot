[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$SqlitePath = "data\sqlite\forward-shadow.sqlite3",
    [string]$Reason = "operator stop",
    [int]$TimeoutSeconds = 180,
    # Last resort after the timeout. Killing a run inside a cycle latches its
    # SQLite permanently (exit 4 on every later run), so it is never the default.
    [switch]$Force
)

# Stops the paper-only forward-shadow run on one SQLite, and the watchdog that
# would relaunch it, without interrupting a paper cycle: the run is asked to
# stop (--mode stop-shadow) and exits between cycles; the watchdog sees the
# stop file or the run's exit code 0 and ends. No broker order exists to cancel.
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run scripts\windows_setup.ps1 first."
}
if (-not (Test-Path -LiteralPath $SqlitePath -PathType Leaf)) {
    throw "SQLite not found: $SqlitePath. Nothing was stopped."
}
$sqliteFull = (Resolve-Path -LiteralPath $SqlitePath).Path
$runtimeDir = Join-Path $repoRoot "data\runtime"
$watchdogPidFile = Join-Path $runtimeDir "forward-shadow-watchdog.pid"
$watchdogStopFile = Join-Path $runtimeDir "forward-shadow-watchdog.stop"

function Get-ForwardShadowRun {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -match 'agi_style_forex_bot_mt5\.cli' -and
        $_.CommandLine -match '--mode\s+forward-shadow' -and
        ($_.CommandLine.IndexOf($SqlitePath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
         $_.CommandLine.IndexOf($sqliteFull, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
}

function Get-Watchdog {
    if (-not (Test-Path -LiteralPath $watchdogPidFile)) { return $null }
    $watchdogPid = Get-Content -LiteralPath $watchdogPidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($watchdogPid -notmatch '^\d+$') { return $null }
    $process = Get-Process -Id ([int]$watchdogPid) -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -in @("powershell", "pwsh")) { return $process }
    return $null
}

$runs = Get-ForwardShadowRun
if ($runs.Count -eq 0 -and -not (Get-Watchdog)) {
    Write-Host "No forward-shadow run or watchdog found for $sqliteFull. Nothing was stopped."
    exit 1
}

# 1) The watchdog must not relaunch the run once it ends.
if (Get-Watchdog) {
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    Set-Content -LiteralPath $watchdogStopFile -Value $Reason -Encoding ascii
    Write-Host "Watchdog asked to stop."
}

# 2) Ask the run to stop between cycles; it finishes the current one first.
if ($runs.Count -gt 0) {
    $env:PYTHONPATH = "src/python"
    & $venvPython -m agi_style_forex_bot_mt5.cli --mode stop-shadow --sqlite $SqlitePath --reason $Reason
    if ($LASTEXITCODE -ne 0) {
        throw "stop-shadow failed with exit code $LASTEXITCODE. Nothing was stopped."
    }
}

# 3) Wait for both to end.
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while (((Get-ForwardShadowRun).Count -gt 0 -or (Get-Watchdog)) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
}
$runs = Get-ForwardShadowRun
$watchdog = Get-Watchdog
if ($runs.Count -eq 0 -and -not $watchdog) {
    Write-Host "forward-shadow stopped cleanly; open paper positions are kept. Start it again the same way."
    exit 0
}
if (-not $Force) {
    Write-Host "Still running after $TimeoutSeconds s (a cycle or MT5 read may be slow). The stop request stays pending;"
    Write-Host "run this script again later, or add -Force to kill it (risk: a kill inside a cycle latches this SQLite)."
    exit 1
}
foreach ($process in $runs) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Killed forward-shadow PID $($process.ProcessId)"
}
if ($watchdog) {
    Stop-Process -Id $watchdog.Id -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $watchdogPidFile, $watchdogStopFile -ErrorAction SilentlyContinue
    Write-Host "Killed watchdog PID $($watchdog.Id)"
}
Write-Host "Forced stop. Check '--mode status' before restarting: a latch (exit 4) needs a new SQLite."
exit 0
