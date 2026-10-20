[CmdletBinding()]
param(
    [switch]$Setup,
    [switch]$Check
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$app = Join-Path $PSScriptRoot "risk_calculator_app.pyw"
$requirements = Join-Path $PSScriptRoot "requirements-mt5.txt"

if ($Setup) {
    if (-not (Test-Path -LiteralPath $python)) {
        if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
            throw "Install Python 3.12 (64-bit) with the Python launcher, then retry -Setup."
        }
        & py -3.12 -c "import struct, tkinter; assert struct.calcsize('P') == 8, 'Python must be 64-bit'"
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.12 (64-bit) with Tkinter is required."
        }
        & py -3.12 -m venv (Join-Path $PSScriptRoot ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the local Python environment."
        }
    }
    & $python -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) {
        throw "MT5 dependency installation failed. Check internet access and Python compatibility."
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Local Python environment is missing. Run .\Start-RiskPlanner.ps1 -Setup first."
}

& $python -c "import sys, struct, tkinter, MetaTrader5; assert sys.version_info >= (3, 10), 'Python 3.10+ required'; assert struct.calcsize('P') == 8, 'Python must be 64-bit'; print('Python:', sys.version.split()[0], '| MetaTrader5:', MetaTrader5.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "Environment check failed. Run .\Start-RiskPlanner.ps1 -Setup and inspect the error above."
}

if ($Setup -or $Check) {
    Write-Host "Environment ready. This check does not connect to MT5 or place trades."
    Write-Host "Open and log in to the MT5 terminal on this laptop, then run .\Start-RiskPlanner.ps1."
    return
}

& $python $app
if ($LASTEXITCODE -ne 0) {
    throw "Risk Planner exited with an error. Review the Python output above."
}
