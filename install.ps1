<#
.SYNOPSIS
  UltraCode-Shim installer for Windows.

.DESCRIPTION
  One command turns a fresh machine into "type `ultracode`, pick a model, go":
  it gets the code, verifies it with the offline self-test, creates your
  config.json, and installs a small `ultracode` command on your PATH.

  Run it either way:

    # straight from the web (PowerShell):
    irm https://raw.githubusercontent.com/OnlyTerp/UltraCode-Shim/main/install.ps1 | iex

    # or from inside a clone:
    .\install.ps1

  Nothing here needs admin, touches your global Claude config, or pip-installs
  anything (the proxy is pure standard library).

.PARAMETER Dir
  Where to clone if you're not already in a checkout.
  Default: $env:UC_INSTALL_DIR or %LOCALAPPDATA%\UltraCode-Shim.

.PARAMETER BinDir
  Where to install the `ultracode` command.
  Default: $env:UC_BIN_DIR or %LOCALAPPDATA%\Microsoft\WindowsApps (already on PATH)
  falling back to %LOCALAPPDATA%\UltraCode-Shim\bin.

.PARAMETER NoTest
  Skip the offline self-test.

.PARAMETER DesktopIcons
  Also create the Desktop shortcuts (UltraCode + normal Claude Code).

.PARAMETER Uninstall
  Remove the `ultracode` command shim (leaves your clone + config).
#>
[CmdletBinding()]
param(
    [string]$Dir = "",
    [string]$BinDir = "",
    [switch]$NoTest,
    [switch]$DesktopIcons,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/OnlyTerp/UltraCode-Shim.git"

function Info($m) { Write-Host "==> $m" -ForegroundColor Magenta }
function Ok($m)   { Write-Host "  ok $m" -ForegroundColor Green }
function Warn($m) { Write-Host "warn $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "FAIL $m" -ForegroundColor Red; exit 1 }

if (-not $Dir)    { $Dir    = if ($env:UC_INSTALL_DIR) { $env:UC_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "UltraCode-Shim" } }
if (-not $BinDir) {
    $BinDir = if ($env:UC_BIN_DIR) { $env:UC_BIN_DIR }
              else {
                  $winApps = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
                  if (Test-Path $winApps) { $winApps } else { Join-Path $Dir "bin" }
              }
}

# ----- locate Python --------------------------------------------------------
function Find-Python {
    foreach ($cand in @(@("py","-3"), @("python"), @("python3"))) {
        if (Get-Command $cand[0] -ErrorAction SilentlyContinue) { return ,$cand }
    }
    return $null
}
$PyCmd = Find-Python
if (-not $PyCmd) { Die "Python 3 not found. Install from https://www.python.org/downloads/ (tick 'Add Python to PATH') and re-run." }
$PyOk = (& $PyCmd[0] @($PyCmd[1..($PyCmd.Count-1)] + @("-c","import sys;print(1 if sys.version_info>=(3,8) else 0)"))) 2>$null
if ("$PyOk".Trim() -ne "1") { Die "Python 3.8+ is required." }

# ----- find the repo (local checkout vs. clone) -----------------------------
function Test-Repo($p) { return ($p -and (Test-Path (Join-Path $p "proxy.py")) -and (Test-Path (Join-Path $p "bin\ultracode"))) }

$ScriptDir = ""
if ($PSCommandPath) { $ScriptDir = Split-Path -Parent $PSCommandPath }

$Repo = $null
if (Test-Repo $ScriptDir) {
    $Repo = $ScriptDir
    Info "Using this checkout: $Repo"
} elseif (Test-Repo (Get-Location).Path) {
    $Repo = (Get-Location).Path
    Info "Using this checkout: $Repo"
} else {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Die "git not found. Install Git for Windows, or download the repo and run .\install.ps1 from inside it."
    }
    if (Test-Repo $Dir) {
        Info "Updating existing clone at $Dir"
        try { git -C $Dir pull --ff-only --quiet } catch { Warn "could not fast-forward; using the existing clone as-is" }
    } else {
        Info "Cloning $RepoUrl -> $Dir"
        New-Item -ItemType Directory -Force -Path (Split-Path $Dir) | Out-Null
        git clone --depth 1 --quiet $RepoUrl $Dir
        if ($LASTEXITCODE -ne 0) { Die "git clone failed" }
    }
    $Repo = $Dir
}
if (-not (Test-Repo $Repo)) { Die "internal: '$Repo' is not a valid UltraCode-Shim checkout" }

# ----- uninstall path -------------------------------------------------------
if ($Uninstall) {
    $removed = $false
    foreach ($d in @($BinDir, (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"), (Join-Path $Dir "bin"))) {
        foreach ($name in @("ultracode.cmd","ultracode")) {
            $shim = Join-Path $d $name
            if (Test-Path $shim) { Remove-Item $shim -Force; Ok "removed $shim"; $removed = $true }
        }
    }
    if (-not $removed) { Warn "no ultracode command found in the usual bin dirs" }
    Write-Host "Your clone ($Repo) and config.json were left untouched."
    exit 0
}

# ----- offline self-test (free ports) ---------------------------------------
if (-not $NoTest -and (Test-Path (Join-Path $Repo "test_proxy.py"))) {
    Info "Running the offline self-test (no network, no keys)..."
    # The test prints progress on stderr; under -ErrorActionPreference Stop that
    # would otherwise be promoted to a terminating error, so relax it locally and
    # gate purely on the process exit code.
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $portScript = "import socket" + [char]10 +
                      "def f():" + [char]10 +
                      "    s=socket.socket(); s.bind(('127.0.0.1',0)); p=s.getsockname()[1]; s.close(); return p" + [char]10 +
                      "print(f(), f())"
        $ports = & $PyCmd[0] @($PyCmd[1..($PyCmd.Count-1)] + @("-c", $portScript)) 2>$null
        $p1, $p2 = ("$ports".Trim() -split "\s+")
        if (-not $p1 -or -not $p2) { $p1 = 8741; $p2 = 8742 }
        $env:UC_TEST_PROXY_PORT = "$p1"; $env:UC_TEST_MOCK_PORT = "$p2"
        $out = & $PyCmd[0] @($PyCmd[1..($PyCmd.Count-1)] + @((Join-Path $Repo "test_proxy.py"))) 2>&1
        $rc = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    if ($rc -eq 0) {
        Ok "self-test passed (proxy, discovery, UltraCode envelope, tool translation)"
    } else {
        $out | ForEach-Object { Write-Host "    $_" }
        Die "self-test failed -- the clone looks broken. Please open an issue with the output above."
    }
}

# ----- config.json ----------------------------------------------------------
$Config = Join-Path $Repo "config.json"
if (-not (Test-Path $Config)) {
    Copy-Item (Join-Path $Repo "config.example.json") $Config
    Ok "created config.json from the example (edit it to keep the models you have)"
} else {
    Ok "config.json already exists -- leaving it as-is"
}

# ----- install the `ultracode` command on PATH ------------------------------
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Shim = Join-Path $BinDir "ultracode.cmd"
$RepoCmd = Join-Path $Repo "bin\ultracode.cmd"
$shimBody = @(
    '@echo off',
    'REM UltraCode-Shim launcher (generated by install.ps1). Points at your checkout.',
    "call `"$RepoCmd`" %*"
) -join "`r`n"
Set-Content -Path $Shim -Value $shimBody -Encoding ascii
Ok "installed command: $Shim -> $RepoCmd"

if ($DesktopIcons) {
    try {
        & (Join-Path $Repo "windows\Install-DesktopIcons.ps1")
    } catch { Warn "could not create Desktop icons: $_" }
}

# ----- PATH guidance --------------------------------------------------------
$onPath = (($env:PATH -split ';') -contains $BinDir) -or
          (($env:PATH -split ';') -contains ($BinDir.TrimEnd('\')))

Write-Host ""
Info "Done. UltraCode-Shim is installed."
Write-Host ""
if ($onPath) {
    Write-Host "  Launch it from anywhere:   ultracode"
} else {
    Warn "$BinDir is not on your PATH yet."
    Write-Host "  Add it for your user (then open a new terminal):"
    Write-Host "    [Environment]::SetEnvironmentVariable('PATH', `"`$env:PATH;$BinDir`", 'User')"
    Write-Host "  Or launch with the full path for now:"
    Write-Host "    $Shim"
}
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    1. Configure your models: edit $Config"
Write-Host "       (keep the backends you have a key/plan for; delete the rest)."
Write-Host "    2. Sanity-check it:      $($PyCmd[0]) $Repo\scripts\doctor.py"
Write-Host "    3. Run it:               ultracode   (pick orchestrator + worker, then /model anytime)"
Write-Host ""
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Warn "Claude Code CLI not found yet -- install it before launching:  npm i -g @anthropic-ai/claude-code"
}
