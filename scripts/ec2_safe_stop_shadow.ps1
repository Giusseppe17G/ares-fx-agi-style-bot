param(
    [string]$SqlitePath = "data\sqlite\forward-shadow-stable.sqlite3",
    [string]$Reason = "EC2 operator safe stop"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "py" }

$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode pause-shadow --sqlite $SqlitePath --reason $Reason
Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match "agi_style_forex_bot_mt5\.cli" -and
        $_.CommandLine -match "--mode\s+forward-shadow" -and
        $_.CommandLine -match "--signal-profile\s+BALANCED_STABLE"
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force
    }
exit $LASTEXITCODE
