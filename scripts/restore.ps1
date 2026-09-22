[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Archive, [switch]$ConfirmRestore)
$ErrorActionPreference = 'Stop'
if (-not $ConfirmRestore) { throw 'Restore can overwrite local data. Review the archive, then rerun with -ConfirmRestore.' }
if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) { throw "Backup archive not found: $Archive" }
$dataDir = if ($env:CAREERFORGE_DATA_DIR) { $env:CAREERFORGE_DATA_DIR } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'CareerForge' } else { Join-Path $HOME '.careerforge' }
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $dataDir -Force
Write-Host "Restored archive to: $dataDir"
