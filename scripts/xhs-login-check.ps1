# Scheduled login observation: memory only; no login, page navigation, or alerts.
param(
  [string]$RepoDir = (Split-Path $PSScriptRoot -Parent),
  [string]$LogPath = (Join-Path $env:USERPROFILE '.link-brain\login-check.log'),
  [string]$PythonExe = 'python'
)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $RepoDir
try {
  $result = & $PythonExe -m link_brain login --status --shallow --json
  $code = $LASTEXITCODE
  $state = try { ($result | ConvertFrom-Json).login_state } catch { 'unknown' }
  $parent = Split-Path $LogPath -Parent
  if (!(Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  Add-Content -LiteralPath $LogPath -Value ("{0:o} login_state={1} exit={2}" -f (Get-Date), $state, $code)
} finally { Pop-Location }
