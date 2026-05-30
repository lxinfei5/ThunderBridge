#Requires -Version 5.1
<#
.SYNOPSIS
  Install UltraCode Windows .cmd launchers and Desktop shortcuts.

.DESCRIPTION
  Copies launchers to %USERPROFILE%\.terp\launchers and creates .lnk shortcuts
  on the Desktop. Each shortcut opens Claude Code UltraCode routed to a chosen
  backend (MiMo, Composer, etc.) via WSL.

.PARAMETER DesktopPath
  Where to create .lnk files. Defaults to OneDrive Desktop if present.

.PARAMETER WslDistro
  WSL distribution name. Default: Ubuntu

.PARAMETER WslWorkdir
  WSL working directory passed to wsl.exe --cd. Default: ~/repos
#>
param(
    [string]$DesktopPath = "",
    [string]$WslDistro = "Ubuntu",
    [string]$WslWorkdir = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LauncherSrc = Join-Path $RepoRoot "launchers"
$LauncherDst = Join-Path $env:USERPROFILE ".terp\launchers"

if (-not $DesktopPath) {
    $oneDrive = Join-Path $env:USERPROFILE "OneDrive\Desktop"
    $regular = [Environment]::GetFolderPath("Desktop")
    $DesktopPath = if (Test-Path $oneDrive) { $oneDrive } else { $regular }
}

if (-not $WslWorkdir) {
    $WslWorkdir = Join-Path $env:USERPROFILE "repos"
}

New-Item -ItemType Directory -Force -Path $LauncherDst | Out-Null

Get-ChildItem -Path $LauncherSrc -Filter "*.cmd" | ForEach-Object {
    Copy-Item -Force $_.FullName (Join-Path $LauncherDst $_.Name)
    Write-Host "copied launcher: $($_.Name)"
}

$CursorIcon = Join-Path $env:LOCALAPPDATA "Programs\cursor\resources\app\resources\win32\code.ico"
$XiaomiIcon = Join-Path $env:USERPROFILE "Downloads\Xiaomi_logo_(2021-).svg.ico"
$WtIcon = "${env:ProgramFiles}\WindowsApps\Microsoft.WindowsTerminal_*\wt.exe"

$WtResolved = Get-ChildItem -Path (Split-Path $WtIcon) -Filter "wt.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending |
    Select-Object -First 1

$Presets = @(
    @{
        Name       = "MiMo v2.5 Pro UltraCode VIDEO"
        CmdFile    = "Claude MiMo UltraCode VIDEO.cmd"
        Icon       = if (Test-Path $XiaomiIcon) { "$XiaomiIcon,0" } else { "" }
    },
    @{
        Name       = "Composer 2.5 Fast UltraCode VIDEO"
        CmdFile    = "Claude Composer 2.5 Fast UltraCode VIDEO.cmd"
        Icon       = if (Test-Path $CursorIcon) { "$CursorIcon,0" } else { "" }
    },
    @{
        Name       = "Claude MiMo UltraCode"
        CmdFile    = "Claude MiMo UltraCode.cmd"
        Icon       = if ($WtResolved) { "$($WtResolved.FullName),0" } else { "" }
    }
)

$Shell = New-Object -ComObject WScript.Shell

foreach ($preset in $Presets) {
    $cmdPath = Join-Path $LauncherDst $preset.CmdFile
    if (-not (Test-Path $cmdPath)) {
        Write-Warning "missing launcher: $cmdPath — skipping $($preset.Name)"
        continue
    }

    $lnkPath = Join-Path $DesktopPath "$($preset.Name).lnk"
    $shortcut = $Shell.CreateShortcut($lnkPath)
    $shortcut.TargetPath = $cmdPath
    $shortcut.WorkingDirectory = $DesktopPath
    $shortcut.WindowStyle = 1
    if ($preset.Icon) {
        $shortcut.IconLocation = $preset.Icon
    }
    $shortcut.Save()
    Write-Host "created shortcut: $lnkPath"
}

Write-Host ""
Write-Host "Done. Double-click a Desktop icon to launch UltraCode with your chosen backend."
Write-Host "Ensure WSL launchers are installed: ./scripts/install.sh"
