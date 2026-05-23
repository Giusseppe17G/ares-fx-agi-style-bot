param(
    [string]$SqlitePath = "data\sqlite\forward-shadow-stable.sqlite3",
    [string]$LogDir = "data\logs\forward-shadow-stable",
    [string]$ReportsRoot = "data\reports"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "py" }

$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode forward-evidence --sqlite $SqlitePath --log-dir $LogDir --reports-root $ReportsRoot --output-dir "$ReportsRoot\forward_evidence"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode forward-acceptance --sqlite $SqlitePath --log-dir $LogDir --reports-root $ReportsRoot --output-dir "$ReportsRoot\forward_evidence"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode paper-state-report --sqlite $SqlitePath --log-dir $LogDir --output-dir "$ReportsRoot\paper_state"
exit $LASTEXITCODE
