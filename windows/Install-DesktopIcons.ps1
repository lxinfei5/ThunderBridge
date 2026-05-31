<#
.SYNOPSIS
  Create Desktop shortcuts for UltraCode-Shim.

.DESCRIPTION
  Creates two icons so you can choose per-launch and never touch your normal
  setup by accident:

    * "UltraCode (All Models)"  -> runs windows\Start-UltraCode.ps1 (proxy on,
                                   /model lists all your backends).
    * "Claude Code (Normal)"    -> plain `claude`, no proxy, your usual install.

.PARAMETER DesktopPath
  Where to write the .lnk files. Defaults to OneDrive Desktop if present, else
  the normal Desktop.

.EXAMPLE
  .\windows\Install-DesktopIcons.ps1
#>
param(
    [string]$DesktopPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$StartPs1 = Join-Path $PSScriptRoot "Start-UltraCode.ps1"
$AssetsDir = Join-Path $RepoRoot "assets\icons"

if (-not $DesktopPath) {
    $oneDrive = Join-Path $env:USERPROFILE "OneDrive\Desktop"
    $DesktopPath = if (Test-Path $oneDrive) { $oneDrive } else { [Environment]::GetFolderPath("Desktop") }
}
if (-not (Test-Path $DesktopPath)) { throw "Desktop path not found: $DesktopPath" }

$PwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue)
$PsExe = if ($PwshExe) { $PwshExe.Source } else { Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe" }
$Cmd = Join-Path $env:SystemRoot "System32\cmd.exe"
$Shell = New-Object -ComObject WScript.Shell

function New-Icon {
    param([string]$Name, [string]$Target, [string]$Arguments, [string]$Icon)
    $lnk = Join-Path $DesktopPath "$Name.lnk"
    $sc = $Shell.CreateShortcut($lnk)
    $sc.TargetPath = $Target
    $sc.Arguments = $Arguments
    $sc.WorkingDirectory = $RepoRoot
    $sc.WindowStyle = 1
    if ($Icon -and (Test-Path $Icon)) { $sc.IconLocation = "$Icon,0" }
    $sc.Save()
    Write-Host "created: $lnk"
}

New-Icon -Name "UltraCode (All Models)" `
    -Target $PsExe `
    -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$StartPs1`"" `
    -Icon (Join-Path $AssetsDir "ultracode.ico")

New-Icon -Name "Claude Code (Normal)" `
    -Target $Cmd `
    -Arguments "/k claude" `
    -Icon (Join-Path $AssetsDir "claude.ico")

Write-Host ""
Write-Host "Done. Two Desktop icons created in: $DesktopPath" -ForegroundColor Green
Write-Host "Double-click 'UltraCode (All Models)', then type /model to pick a backend."
