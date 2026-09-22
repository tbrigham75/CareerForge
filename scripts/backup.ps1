[CmdletBinding()]
param([string]$Destination = '')
$ErrorActionPreference = 'Stop'
$dataDir = if ($env:CAREERFORGE_DATA_DIR) { $env:CAREERFORGE_DATA_DIR } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'CareerForge' } else { Join-Path $HOME '.careerforge' }
if (-not (Test-Path $dataDir)) { throw "CareerForge data directory does not exist: $dataDir" }
if (-not $Destination) { $Destination = Join-Path $dataDir 'backups' }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archive = Join-Path $Destination "CareerForge-$stamp.zip"
Compress-Archive -Path (Join-Path $dataDir '*') -DestinationPath $archive -CompressionLevel Optimal
Write-Host "Created backup: $archive"
