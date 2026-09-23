[CmdletBinding()]
param([switch]$SeedExampleData)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
function Invoke-Checked([scriptblock]$Command) {
  & $Command
  if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE." }
}
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Python Launcher (py) is required. Install Python 3.12 or 3.13 from python.org.' }
Invoke-Checked { py -3.13 --version }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git for Windows is required.' }
if (-not (Test-Path '.venv\Scripts\python.exe')) { Invoke-Checked { py -3.13 -m venv .venv } }
Invoke-Checked { & .\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple --upgrade pip }
Invoke-Checked { & .\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r requirements-dev.txt }
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
$environment = Get-Content '.env' -Raw
if ($environment -notmatch '(?m)^CAREERFORGE_ENCRYPTION_KEY=[^\s\r\n]+$') {
  $key = & .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  $withoutKeys = [regex]::Replace($environment, '(?m)^CAREERFORGE_ENCRYPTION_KEY=.*\r?\n?', '')
  Set-Content '.env' ($withoutKeys.TrimEnd() + "`nCAREERFORGE_ENCRYPTION_KEY=$key`n") -NoNewline
}
$dataDir = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'CareerForge' } else { Join-Path $HOME '.careerforge' }
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$env:PYTHONPATH = (Join-Path $root 'backend')
Invoke-Checked { & .\.venv\Scripts\python.exe -m app.migrate }
if ($SeedExampleData) { Invoke-Checked { & $PSScriptRoot\seed-example-data.ps1 } }
Write-Host 'CareerForge is bootstrapped. Run .\scripts\run-dev.ps1 and open http://127.0.0.1:8000'
