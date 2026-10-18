[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "web"

function Resolve-Node {
    if ($env:COURSEMATE_NODE) { return $env:COURSEMATE_NODE }
    $command = Get-Command node -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $fallback = "C:\Users\28260\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
    if (Test-Path $fallback) { return $fallback }
    throw "Node.js not found. Install Node 20+ or set COURSEMATE_NODE."
}

function Resolve-Pnpm {
    if ($env:COURSEMATE_PNPM) {
        $path = $env:COURSEMATE_PNPM
        return @{ Path = $path; UseNode = ($path -like "*.mjs" -or $path -like "*.js") }
    }
    $command = Get-Command pnpm -ErrorAction SilentlyContinue
    if ($command) { return @{ Path = $command.Source; UseNode = $false } }
    $fallback = "C:\Users\28260\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.mjs"
    if (Test-Path $fallback) { return @{ Path = $fallback; UseNode = $true } }
    throw "pnpm not found. Install pnpm 9+ or set COURSEMATE_PNPM."
}

$node = Resolve-Node
$env:PATH = "$(Split-Path -Parent $node);$env:PATH"
$pnpm = Resolve-Pnpm

function Invoke-Pnpm {
    param([string[]]$Arguments)
    if ($pnpm.UseNode) {
        & $node $pnpm.Path @Arguments
    }
    else {
        & $pnpm.Path @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "pnpm failed (exit code $LASTEXITCODE)"
    }
}

Push-Location $web
try {
    Write-Host "[web] installing dependencies ..."
    Invoke-Pnpm @("install")
    Write-Host "[web] building ..."
    Invoke-Pnpm @("run", "build")
}
finally {
    Pop-Location
}

Write-Host "[web] built: $(Join-Path $web 'dist')"
