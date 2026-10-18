[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    throw "No .venv found. Run first: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1"
}

Push-Location (Join-Path $root "backend")
try {
    Write-Host "[run] CourseMate: http://127.0.0.1:$Port"
    & $venvPy -m uvicorn app.server:app --host 127.0.0.1 --port $Port
}
finally {
    Pop-Location
}
