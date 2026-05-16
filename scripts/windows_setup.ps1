param(
    [string]$PythonLauncher = "py",
    [string]$VenvPath = ".\.venv"
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format o)] $Message"
}

Write-Step "Checking Python 3.11+ availability"
$pythonVersionOutput = & $PythonLauncher -3 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Python launcher '$PythonLauncher' is not available. Install Python 3.11+ first."
}

if ($pythonVersionOutput -notmatch "Python\s+(\d+)\.(\d+)\.") {
    throw "Unable to parse Python version: $pythonVersionOutput"
}

$major = [int]$Matches[1]
$minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "Python 3.11+ is required. Found: $pythonVersionOutput"
}
Write-Step "Found $pythonVersionOutput"

if (-not (Test-Path $VenvPath)) {
    Write-Step "Creating virtual environment at $VenvPath"
    & $PythonLauncher -3 -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment"
    }
}

$venvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment Python not found: $venvPython"
}

Write-Step "Upgrading pip"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip"
}

Write-Step "Installing project dependencies with dev and MT5 extras"
& $venvPython -m pip install -e ".[dev,mt5]"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install project dependencies"
}

Write-Step "Verifying MetaTrader5 import"
& $venvPython -c "import MetaTrader5; print('MetaTrader5 import OK')"
if ($LASTEXITCODE -ne 0) {
    throw "MetaTrader5 import failed. Install the MetaTrader5 Python package and confirm the venv is active."
}

$folders = @(
    "data\logs",
    "data\sqlite",
    "data\reports"
)
foreach ($folder in $folders) {
    if (-not (Test-Path $folder)) {
        Write-Step "Creating $folder"
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
    }
}

Write-Step "Setup complete. No secrets were requested or stored."
