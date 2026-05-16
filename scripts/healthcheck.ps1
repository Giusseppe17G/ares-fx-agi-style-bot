param(
    [string]$LogRoot = "data\logs",
    [string]$SqlitePath = "data\sqlite\mt5-data-ec2.sqlite3",
    [int]$MinimumFreeDiskGB = 5
)

$ErrorActionPreference = "Continue"
$status = "OK"
$messages = New-Object System.Collections.Generic.List[string]

function Add-Status {
    param(
        [string]$Level,
        [string]$Message
    )
    $script:messages.Add("$Level: $Message")
    if ($Level -eq "CRITICAL") {
        $script:status = "CRITICAL"
    } elseif ($Level -eq "WARNING" -and $script:status -ne "CRITICAL") {
        $script:status = "WARNING"
    }
}

$terminal = Get-Process -Name terminal64 -ErrorAction SilentlyContinue
if ($terminal) {
    Add-Status "OK" "MetaTrader 5 terminal64.exe is running"
} else {
    Add-Status "WARNING" "MetaTrader 5 terminal64.exe is not running"
}

$botProcesses = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match "agi_style_forex_bot_mt5\.cli" -and
        $_.CommandLine -match "--mode\s+mt5-data"
    }
if ($botProcesses) {
    Add-Status "OK" "mt5-data bot process detected"
} else {
    Add-Status "WARNING" "mt5-data bot process not detected"
}

$latestJsonl = Get-ChildItem -Path $LogRoot -Recurse -Filter "*.jsonl" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($latestJsonl) {
    Add-Status "OK" "Latest JSONL: $($latestJsonl.FullName)"
    $lastLine = Get-Content $latestJsonl.FullName -Tail 1 -ErrorAction SilentlyContinue
    if ($lastLine -match '"event_type"\s*:\s*"CRITICAL_ERROR"') {
        Add-Status "CRITICAL" "Latest JSONL event is CRITICAL_ERROR"
    }
} else {
    Add-Status "WARNING" "No JSONL logs found under $LogRoot"
}

if (Test-Path $SqlitePath) {
    Add-Status "OK" "SQLite database exists: $SqlitePath"
} else {
    Add-Status "WARNING" "SQLite database missing: $SqlitePath"
}

$drive = Get-PSDrive -Name (Get-Location).Drive.Name
$freeGb = [math]::Round($drive.Free / 1GB, 2)
if ($freeGb -lt $MinimumFreeDiskGB) {
    Add-Status "CRITICAL" "Low disk space: $freeGb GB free"
} else {
    Add-Status "OK" "Disk free: $freeGb GB"
}

$os = Get-CimInstance Win32_OperatingSystem
$freeMemMb = [math]::Round($os.FreePhysicalMemory / 1024, 0)
Add-Status "OK" "Approx free memory: $freeMemMb MB"

Write-Host "STATUS=$status"
$messages | ForEach-Object { Write-Host $_ }

if ($status -eq "CRITICAL") {
    exit 2
}
if ($status -eq "WARNING") {
    exit 1
}
exit 0
