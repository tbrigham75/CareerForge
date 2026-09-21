[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    throw 'Create the local virtual environment and install the development dependencies first.'
}

Push-Location $projectRoot
try {
    # This only writes build artifacts beneath the checkout. It needs no administrator rights.
    & $python -m PyInstaller --noconfirm --clean --onefile --name CareerForge --collect-all uvicorn --collect-all fastapi careerforge\launcher.py
} finally {
    Pop-Location
}

Write-Host 'Built dist\CareerForge.exe. End users run this file directly; it includes Python and application dependencies.'
