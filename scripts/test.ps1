[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    throw "No .venv found. Run first: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1"
}

# Sandbox compatibility for os.mkdir(0o700); test process only.
$env:PYTHONPATH = (Join-Path $PSScriptRoot "pysite")

Push-Location (Join-Path $root "backend")
try {
    & $venvPy -m pytest @PytestArgs
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $code
