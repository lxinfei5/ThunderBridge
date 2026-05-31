<#
.SYNOPSIS
  Launch Claude Code in UltraCode mode with the UltraCode-Shim model proxy, so
  the /model picker lists every backend you configured and any of them runs with
  full UltraCode behavior.

.DESCRIPTION
  Starts gateway/ultracode_proxy.py on a loopback port, points Claude Code at it
  via ANTHROPIC_BASE_URL, enables gateway model discovery, seeds the discovery
  cache so your models show on first open, then runs `claude`. When Claude Code
  exits, the proxy is stopped.

  Your normal Claude Code install is untouched: this only sets environment for
  THIS process and uses a session-scoped --settings file.

.PARAMETER ProxyOnly
  Start the proxy and print how to connect, but don't launch Claude Code.

.PARAMETER Port
  Loopback port for the proxy. Default 8141.

.EXAMPLE
  .\windows\Start-UltraCode.ps1
#>
param(
    [switch]$ProxyOnly,
    [int]$Port = 8141,
    [string]$Upstream = "https://api.anthropic.com"
)

$ErrorActionPreference = "Stop"
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$Gateway    = Join-Path $RepoRoot "gateway"
$Proxy      = Join-Path $Gateway "ultracode_proxy.py"
$ConfigDir  = Join-Path $RepoRoot "config"
$SlotsFile  = Join-Path $ConfigDir "ultracode_slots.json"
$ModelsFile = Join-Path $ConfigDir "ultracode_models.json"
$EnvFile    = Join-Path $ConfigDir "ultracode.env"

# ----- locate Python --------------------------------------------------------
function Find-Python {
    foreach ($cand in @(@("py","-3"), @("python"), @("python3"))) {
        $exe = $cand[0]
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            return ,$cand
        }
    }
    throw "Python 3 not found. Install it from https://www.python.org/downloads/ (check 'Add to PATH')."
}
$PyCmd = Find-Python

# ----- locate Claude Code ---------------------------------------------------
$Claude = (Get-Command claude -ErrorAction SilentlyContinue)
if (-not $Claude) {
    throw "Claude Code CLI not found. Install it with: npm i -g @anthropic-ai/claude-code"
}

# ----- ensure config exists (copy from examples on first run) ---------------
if (-not (Test-Path $SlotsFile))  { Copy-Item (Join-Path $ConfigDir "ultracode_slots.example.json")  $SlotsFile }
if (-not (Test-Path $ModelsFile)) { Copy-Item (Join-Path $ConfigDir "ultracode_models.example.json") $ModelsFile }
if (-not (Test-Path $EnvFile) -and (Test-Path (Join-Path $ConfigDir "ultracode.example.env"))) {
    Copy-Item (Join-Path $ConfigDir "ultracode.example.env") $EnvFile
    Write-Host "Created config\ultracode.env - add your API keys there for any 'openai_compat' backends." -ForegroundColor Yellow
}

# ----- load ultracode.env into this process (for ${VAR} expansion) ----------
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $k, $v = $line.Split("=", 2)
            [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
        }
    }
}

# ----- state dir + session settings -----------------------------------------
$StateDir = Join-Path $env:LOCALAPPDATA "UltraCode-Shim"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$Settings = Join-Path $StateDir "ultracode_settings.json"
$BaseUrl  = "http://127.0.0.1:$Port"
@{
    ultracode = $true
    model     = "claude-opus-4-8"
    env       = @{
        ANTHROPIC_BASE_URL                      = $BaseUrl
        CLAUDE_CODE_WORKFLOWS                   = "1"
        CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = "1"
    }
} | ConvertTo-Json -Depth 5 | Set-Content -Path $Settings -Encoding utf8

# ----- proxy environment ----------------------------------------------------
$env:UC_LISTEN_PORT = "$Port"
$env:UC_UPSTREAM    = $Upstream
$env:UC_SLOT_MAP    = $SlotsFile
$env:UC_MODELS_FILE = $ModelsFile
$env:UC_LOG         = Join-Path $StateDir "ultracode_proxy.log"

# ----- kill any stale proxy on this port ------------------------------------
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" |
    Where-Object { $_.CommandLine -match 'ultracode_proxy\.py' } |
    ForEach-Object {
        Write-Host "Stopping existing UltraCode proxy PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Milliseconds 400

# ----- start the proxy ------------------------------------------------------
Write-Host "Starting UltraCode proxy on $BaseUrl -> $Upstream ..."
$pyArgs = @()
if ($PyCmd.Count -gt 1) { $pyArgs += $PyCmd[1..($PyCmd.Count-1)] }
$pyArgs += $Proxy
$proc = Start-Process -FilePath $PyCmd[0] -ArgumentList $pyArgs -PassThru -WindowStyle Hidden

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 250
    try {
        if ((Invoke-WebRequest -Uri "$BaseUrl/healthz" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) {
            $ready = $true; break
        }
    } catch { }
}
if (-not $ready) {
    Write-Error "Proxy did not become healthy on port $Port. Log: $($env:UC_LOG)"
    if (Test-Path $env:UC_LOG) { Get-Content $env:UC_LOG -Tail 20 }
    exit 1
}
Write-Host "Proxy healthy (pid $($proc.Id))." -ForegroundColor Green

# ----- seed Claude Code's gateway-models cache (first-launch visibility) -----
$CfgDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
$GwCache = Join-Path (Join-Path $CfgDir "cache") "gateway-models.json"
try {
    New-Item -ItemType Directory -Force -Path (Split-Path $GwCache) | Out-Null
    $mj = Get-Content $ModelsFile -Raw | ConvertFrom-Json
    $seed = [ordered]@{
        baseUrl   = $BaseUrl
        fetchedAt = [int64]([datetimeoffset](Get-Date)).ToUnixTimeMilliseconds()
        models    = @($mj.models | ForEach-Object { [ordered]@{ id = $_.id; display_name = $_.display_name } })
    }
    $seed | ConvertTo-Json -Depth 5 | Set-Content -Path $GwCache -Encoding utf8
    Write-Host "Seeded gateway-models cache ($($mj.models.Count) models)."
} catch {
    Write-Host "WARN: could not seed gateway-models cache: $_" -ForegroundColor Yellow
}

if ($ProxyOnly) {
    Write-Host ""
    Write-Host "Proxy running. Connect Claude Code with:"
    Write-Host "  `$env:ANTHROPIC_BASE_URL='$BaseUrl'"
    Write-Host "  claude --settings `"$Settings`""
    Write-Host "Stop the proxy: Stop-Process -Id $($proc.Id)"
    exit 0
}

# ----- launch Claude Code through the proxy ---------------------------------
$env:ANTHROPIC_BASE_URL = $BaseUrl
$env:CLAUDE_CODE_WORKFLOWS = "1"
$env:CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = "1"
Write-Host "Launching Claude Code (UltraCode). Open /model to pick a backend." -ForegroundColor Green
try {
    & $Claude.Source --settings "$Settings" @args
} finally {
    Write-Host "Claude exited. Stopping proxy (pid $($proc.Id))."
    Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue
}
