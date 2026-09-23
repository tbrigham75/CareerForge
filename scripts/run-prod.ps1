$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = (Join-Path $root 'backend')
& .\.venv\Scripts\python.exe -m app.migrate
if ($LASTEXITCODE -ne 0) { throw "Database migration failed with exit code $LASTEXITCODE. The server was not started." }
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
