[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$BuildWeb
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"

function Find-Python {
    param([string]$Preferred)
    if ($Preferred) {
        return (Get-Command $Preferred -ErrorAction Stop).Source
    }
    foreach ($candidate in @("python", "python3")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $version = & $command.Source -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
        if ([version]::Parse($version) -ge [version]"3.12") {
            return $command.Source
        }
    }
    throw "Python 3.12+ not found. Install Python or pass -Python <path>."
}

$pythonExe = Find-Python $Python
Write-Host "[setup] python: $pythonExe"

if (-not (Test-Path $venvPy)) {
    Write-Host "[setup] creating .venv ..."
    & $pythonExe -m venv --without-pip $venv
}
if (-not (Test-Path $venvPy)) {
    throw "Failed to create virtual environment: $venvPy"
}

# This machine's sandbox mishandles os.mkdir(0o700). The patch only applies
# to the installer process and is not used at application runtime.
$env:PYTHONPATH = (Join-Path $PSScriptRoot "pysite")
try {
    Write-Host "[setup] installing backend dependencies ..."
    & $pythonExe -m pip --python $venvPy install --disable-pip-version-check -r (Join-Path $root "backend\requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed (exit code $LASTEXITCODE)"
    }
}
finally {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
}

& $venvPy -c "import fastapi, sqlalchemy, pymupdf, docx, pptx, jwt; print('[setup] backend imports ok')"

if ($BuildWeb) {
    & (Join-Path $PSScriptRoot "build-web.ps1")
}

Write-Host "[setup] done. Start with: powershell -ExecutionPolicy Bypass -File scripts\run.ps1"
