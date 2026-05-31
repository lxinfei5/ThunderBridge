<#
.SYNOPSIS
  Remove UltraCode-Shim Desktop icons and session state.

.DESCRIPTION
  Deletes the two Desktop shortcuts and the LOCALAPPDATA\UltraCode-Shim state
  folder (settings + proxy log). Does NOT touch your config\ files, your Claude
  Code install, or your credentials.
#>
param(
    [string]$DesktopPath = ""
)
$ErrorActionPreference = "SilentlyContinue"

if (-not $DesktopPath) {
    $oneDrive = Join-Path $env:USERPROFILE "OneDrive\Desktop"
    $DesktopPath = if (Test-Path $oneDrive) { $oneDrive } else { [Environment]::GetFolderPath("Desktop") }
}

foreach ($name in @("UltraCode (All Models).lnk", "Claude Code (Normal).lnk")) {
    $p = Join-Path $DesktopPath $name
    if (Test-Path $p) { Remove-Item $p -Force; Write-Host "removed $p" }
}

$StateDir = Join-Path $env:LOCALAPPDATA "UltraCode-Shim"
if (Test-Path $StateDir) { Remove-Item $StateDir -Recurse -Force; Write-Host "removed $StateDir" }

Write-Host "Done. config\ files, Claude Code, and credentials were left untouched."
