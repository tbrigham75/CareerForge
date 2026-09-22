$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& .\.venv\Scripts\python.exe -m ruff check backend tests
& .\.venv\Scripts\python.exe -m mypy backend
& $PSScriptRoot\test.ps1
