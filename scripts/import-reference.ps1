[CmdletBinding()]
param([string]$Source = "Tom's Brag Sheet.odt")
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw "Reference document not found: $Source" }
$env:PYTHONPATH = (Join-Path $root 'backend')
& .\.venv\Scripts\python.exe -m app.import_reference $Source
if ($LASTEXITCODE -ne 0) { throw "Import failed with exit code $LASTEXITCODE." }
