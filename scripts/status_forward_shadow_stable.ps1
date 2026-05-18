param(
    [string]$SqlitePath = "data\sqlite\forward-shadow-stable.sqlite3",
    [string]$StableGate = "data\reports\stable_gate\stable_gate_summary.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run scripts\windows_setup.ps1 first."
}

$env:PYTHONPATH = "src/python"
& $venvPython -m agi_style_forex_bot_mt5.cli --mode stable-health --sqlite $SqlitePath --stable-gate $StableGate
exit $LASTEXITCODE
