[CmdletBinding(PositionalBinding = $false)]
param(
    # Bot configuration outside the repository (DEMO_ONLY=True).
    [Parameter(Mandatory = $true)][string]$Config,
    # Worktree pinned at the freeze commit; by default ..\ares-forward-v1.
    [string]$Worktree = "",
    # Send the messages; TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID come from the environment.
    [switch]$Telegram,
    # Use the exports and swap snapshots already on disk (MT5 closed).
    [switch]$SkipMt5,
    # Only send a test message to check the Telegram setup.
    [switch]$TestTelegram
)

# Weekly routine of the forward paper tracking (research only, no orders):
# export the 9 pairs, capture the broker swap, download new inflation when due,
# run the tracker from the frozen worktree and write the Telegram report.
# Exit codes: 0 done, 2 stopped (the alert says why), 3 MT5 unavailable,
# 4 a Telegram message was not sent (retried on the next run).
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment not found. Run scripts\windows_setup.ps1 first."
    exit 2
}
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    Write-Host "Config file not found: $Config"
    exit 2
}
if (-not $Worktree) {
    $Worktree = Join-Path (Split-Path $repoRoot -Parent) "ares-forward-v1"
}
if (-not $TestTelegram -and -not (Test-Path -LiteralPath $Worktree -PathType Container)) {
    Write-Host "Frozen worktree not found: $Worktree (see docs\COMANDOS_SEGUIMIENTO.md, step 1)."
    exit 2
}

$logDir = Join-Path $repoRoot "data\logs\forward"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "routine-$(Get-Date -Format yyyyMMdd-HHmmss).log"

$env:PYTHONPATH = "src/python"
$arguments = @(
    "-m", "agi_style_forex_bot_mt5.research.daily_fx.forward_routine",
    "--project", $repoRoot,
    "--worktree", $Worktree,
    "--config", (Resolve-Path -LiteralPath $Config).ProviderPath
)
if ($Telegram) { $arguments += "--telegram" }
if ($SkipMt5) { $arguments += "--skip-mt5" }
if ($TestTelegram) { $arguments += "--test-telegram" }

# Python writes errors to stderr; keep them in the log instead of stopping here.
$ErrorActionPreference = "Continue"
& $venvPython @arguments 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log
$code = $LASTEXITCODE
Write-Host "Forward tracking routine exited with code $code (log: $log)"
exit $code
