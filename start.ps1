<#
  start.ps1 -- ultracode-unlock launcher (Windows / PowerShell)

  What it does:
    1. Ensures config.json exists (copies config.example.json on first run).
    2. Reads the listen port from config.json.
    3. Starts proxy.py.
    4. Points Claude Code at the proxy and enables gateway model discovery,
       then launches `claude` in this same shell.

  Usage:
      ./start.ps1            # start proxy + launch claude
      ./start.ps1 -NoClaude  # start proxy only (use your own claude shell)

  The proxy runs in a background job; press Ctrl+C to stop everything.
#>
[CmdletBinding()]
param(
    [switch]$NoClaude
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

$ConfigPath  = Join-Path $Here "config.json"
$ExamplePath = Join-Path $Here "config.example.json"

# 1. First-run: seed config.json from the example.
if (-not (Test-Path $ConfigPath)) {
    if (-not (Test-Path $ExamplePath)) {
        Write-Error "Neither config.json nor config.example.json found in $Here"
        exit 1
    }
    Copy-Item $ExamplePath $ConfigPath
    Write-Host "Created config.json from config.example.json." -ForegroundColor Yellow
    Write-Host "EDIT config.json with your provider + API key, then re-run ./start.ps1" -ForegroundColor Yellow
    exit 0
}

# 2. Read listen port from config.json (default 8141).
$Port = 8141
try {
    $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    if ($cfg.proxy -and $cfg.proxy.listen_port) { $Port = [int]$cfg.proxy.listen_port }
} catch {
    Write-Warning "Could not parse config.json ($_). Using default port $Port."
}

# 3. Find a Python interpreter (prefer a local venv, else python/py).
$Python = $null
foreach ($cand in @(
    (Join-Path $Here ".venv\Scripts\python.exe"),
    (Join-Path $Here "venv\Scripts\python.exe")
)) {
    if (Test-Path $cand) { $Python = $cand; break }
}
if (-not $Python) {
    foreach ($name in @("python", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source; break }
    }
}
if (-not $Python) { Write-Error "No Python interpreter found (need Python 3.8+)."; exit 1 }

# 4. Launch the proxy in a background job.
$ProxyPath = Join-Path $Here "proxy.py"
Write-Host "Starting ultracode-unlock proxy on http://127.0.0.1:$Port ..." -ForegroundColor Cyan
$proxy = Start-Process -FilePath $Python -ArgumentList $ProxyPath `
    -WorkingDirectory $Here -PassThru -NoNewWindow

# Give it a moment, then health-check.
Start-Sleep -Seconds 1
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 5
    Write-Host ("Proxy healthy. Custom models: " +
        (($h.custom_models | ForEach-Object { $_.id }) -join ", ")) -ForegroundColor Green
} catch {
    Write-Warning "Proxy health check failed ($_). It may still be starting."
}

# 5. Point Claude Code at the proxy.
$env:ANTHROPIC_BASE_URL = "http://127.0.0.1:$Port"
$env:CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = "1"
Write-Host "ANTHROPIC_BASE_URL=$($env:ANTHROPIC_BASE_URL)" -ForegroundColor DarkGray

if ($NoClaude) {
    Write-Host "Proxy running (PID $($proxy.Id)). Press Ctrl+C to stop." -ForegroundColor Cyan
    try { Wait-Process -Id $proxy.Id } finally { }
    exit 0
}

# 6. Launch claude in this shell (inherits the env vars above).
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    Write-Warning "`claude` CLI not found on PATH. Proxy is running on port $Port."
    Write-Host "Open a shell with these env vars set and run claude:" -ForegroundColor Yellow
    Write-Host "  `$env:ANTHROPIC_BASE_URL='http://127.0.0.1:$Port'" -ForegroundColor Yellow
    Write-Host "  `$env:CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY='1'" -ForegroundColor Yellow
    try { Wait-Process -Id $proxy.Id } finally { }
    exit 0
}

try {
    & claude @args
} finally {
    Write-Host "Stopping proxy (PID $($proxy.Id))..." -ForegroundColor Cyan
    if (-not $proxy.HasExited) { Stop-Process -Id $proxy.Id -Force -ErrorAction SilentlyContinue }
}
