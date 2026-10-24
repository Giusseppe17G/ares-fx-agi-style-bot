[CmdletBinding(PositionalBinding = $false)]
param(
    # Bot configuration outside the repository (DEMO_ONLY=True).
    [string]$Config = "",
    # When the routine runs each week. The tracker always drops the last bar (it
    # may be forming), so on Monday, after the market reopens, it counts up to
    # Friday and the weekly summary goes out the next day. On Saturday it would
    # only count up to Thursday.
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$Day = "Monday",
    [string]$At = "10:00",
    # Worktree pinned at the freeze commit; by default ..\ares-forward-v1.
    [string]$Worktree = "",
    [string]$TaskName = "AresForwardTracking",
    # Send the messages; set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID with setx first.
    [switch]$Telegram,
    # Delete the scheduled task instead of creating it.
    [switch]$Remove
)

# Registers a weekly Windows task that runs scripts\run_forward_tracking.ps1.
# It runs only while you are logged on, because MT5 needs your desktop session;
# a run missed while the PC was off starts as soon as it is available. After
# setx, sign out and back in so the task sees the Telegram variables.
# Paper tracking only: nothing here reads an account or sends an order.
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Scheduled task $TaskName removed."
    exit 0
}
if (-not $Config -or -not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    Write-Host "Config file not found: $Config"
    exit 2
}
if ($Telegram -and (-not [Environment]::GetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "User") -or
        -not [Environment]::GetEnvironmentVariable("TELEGRAM_CHAT_ID", "User"))) {
    Write-Host "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID with setx first (see docs\COMANDOS_SEGUIMIENTO.md)."
    exit 2
}

$script = Join-Path $repoRoot "scripts\run_forward_tracking.ps1"
$configFull = (Resolve-Path -LiteralPath $Config).ProviderPath
$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Config `"$configFull`""
if ($Worktree) {
    if (-not (Test-Path -LiteralPath $Worktree -PathType Container)) {
        Write-Host "Frozen worktree not found: $Worktree"
        exit 2
    }
    $argument += " -Worktree `"$((Resolve-Path -LiteralPath $Worktree).ProviderPath)`""
}
if ($Telegram) { $argument += " -Telegram" }

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Weekly forward paper tracking (research only, no orders)" -Force | Out-Null
Write-Host "Scheduled task $TaskName registered: every $Day at $At. Test it now with:"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
