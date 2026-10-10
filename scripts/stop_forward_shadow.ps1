param(
    [string]$SqlitePath = "data\sqlite\forward-shadow.sqlite3",
    [string]$Reason = "operator stop"
)

# Stops the generic forward-shadow paper run started by run_forward_shadow.ps1 or
# watchdog_forward_shadow.ps1. Paper only: no broker order exists to cancel.
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run scripts\windows_setup.ps1 first."
}
if (-not (Test-Path -LiteralPath $SqlitePath -PathType Leaf)) {
    throw "SQLite not found: $SqlitePath. Nothing was paused or stopped."
}

# 1) Block new paper entries first; open paper trades stay in the book.
$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode pause-shadow --sqlite $SqlitePath --reason $Reason
if ($LASTEXITCODE -ne 0) {
    throw "pause-shadow failed with exit code $LASTEXITCODE. Nothing was stopped."
}

# 2) Stop the generic watchdog (so it does not relaunch), then the run on this SQLite.
$sqliteFull = (Resolve-Path -LiteralPath $SqlitePath).Path
$targets = @(Get-CimInstance Win32_Process | Where-Object {
    $commandLine = $_.CommandLine
    $commandLine -and (
        ($commandLine -match 'watchdog_forward_shadow\.ps1') -or
        ($commandLine -match 'agi_style_forex_bot_mt5\.cli' -and $commandLine -match '--mode\s+forward-shadow' -and
            ($commandLine.Contains($SqlitePath) -or $commandLine.Contains($sqliteFull)))
    )
})
foreach ($process in $targets) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped PID $($process.ProcessId)"
}
Write-Host "forward-shadow paused and $($targets.Count) process(es) stopped. Before restarting, run --mode resume-shadow on the same SQLite."
