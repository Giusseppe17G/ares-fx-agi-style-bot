[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$LogDir = "data\logs\forward-shadow",
    [string]$SqlitePath = "data\sqlite\forward-shadow.sqlite3",
    [string]$Symbols = "EURUSD,GBPUSD,USDJPY",
    [int]$CycleSeconds = 30,
    [int]$MaxCycles = 0,
    # Optional INI outside the repository (for example MT5_SERVER_TIME=NY_CLOSE).
    [string]$Config = "",
    # Telegram notices; TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID come from the environment.
    [switch]$Telegram
)

# Paper-only forward-shadow run. Exit codes: 0 stopped on request, 2 invalid
# arguments or configuration, 3 MT5 unavailable, 4 paper lifecycle latched,
# 5 MT5 quotes failed integrity checks (see docs/GUIA_DE_USO.md).
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run scripts\windows_setup.ps1 first."
}
if ($Config -and -not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw "Config file not found: $Config"
}

$sqliteParent = Split-Path $SqlitePath -Parent
if (-not $sqliteParent) { $sqliteParent = "." }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $sqliteParent | Out-Null

# One run per SQLite: two writers on the same paper book are refused.
$sqliteFull = Join-Path (Resolve-Path -LiteralPath $sqliteParent).Path (Split-Path $SqlitePath -Leaf)
$existing = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -match 'agi_style_forex_bot_mt5\.cli' -and
    $_.CommandLine -match '--mode\s+forward-shadow' -and
    ($_.CommandLine.Contains($SqlitePath) -or $_.CommandLine.Contains($sqliteFull))
})
if ($existing.Count -gt 0) {
    Write-Host "forward-shadow is already running on $SqlitePath (PID $($existing[0].ProcessId)). Not starting a second run."
    exit 2
}

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
if ($Config) {
    $argsList += @("--config", $Config)
}
if ($Telegram) {
    $argsList += @("--telegram")
}

# Python runs as its own process in this console, not in a PowerShell pipeline:
# PowerShell kills a piped native command on Ctrl+C, possibly inside a paper
# cycle, while this way Python receives Ctrl+C itself and stops between cycles.
$argumentString = ($argsList | ForEach-Object {
    if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
}) -join " "
$errorLog = "$runLog.err"
Write-Host "Running. Ctrl+C once stops it after the current cycle; output is written when it ends."
$process = Start-Process -FilePath $venvPython -ArgumentList $argumentString -NoNewWindow -PassThru `
    -RedirectStandardOutput $runLog -RedirectStandardError $errorLog
$null = $process.Handle  # keeps ExitCode readable after the process ends
$process.WaitForExit()
$exitCode = $process.ExitCode
Get-Content -LiteralPath $runLog, $errorLog -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }

Write-Host "[$(Get-Date -Format o)] forward-shadow finished with exit code $exitCode"
exit $exitCode
