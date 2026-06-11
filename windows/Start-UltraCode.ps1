<#
.SYNOPSIS
  Launch Claude Code in UltraCode mode with the UltraCode-Shim model proxy, so
  the /model picker lists every backend you configured and any of them runs with
  full UltraCode behavior.

.DESCRIPTION
  Starts proxy.py on a loopback port, points Claude Code at it via
  ANTHROPIC_BASE_URL, enables gateway model discovery, seeds the discovery cache
  so your models show on first open, runs the two-column model selector, then
  runs `claude`. When Claude Code exits, this session releases its shared-proxy
  reference; the proxy stops only after the last session exits.

  Your normal Claude Code install is untouched: this only sets environment for
  THIS process and uses a session-scoped --settings file.

.PARAMETER ProxyOnly
  Start the proxy and print how to connect, but don't launch Claude Code.

.PARAMETER Port
  Loopback port for the proxy. 0 (default) reads proxy.listen_port from
  config.json, falling back to 8141.

.EXAMPLE
  .\windows\Start-UltraCode.ps1
#>
param(
    [switch]$ProxyOnly,
    [switch]$Status,
    [int]$Port = 0,
    [string]$Upstream = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot      = Split-Path -Parent $PSScriptRoot
$Proxy         = Join-Path $RepoRoot "proxy.py"
$Config        = Join-Path $RepoRoot "config.json"
$ConfigExample = Join-Path $RepoRoot "config.example.json"
$EnvFile       = Join-Path $RepoRoot "ultracode.env"

# ----- locate Python --------------------------------------------------------
function Find-Python {
    foreach ($cand in @(@("py","-3"), @("python"), @("python3"))) {
        if (Get-Command $cand[0] -ErrorAction SilentlyContinue) { return ,$cand }
    }
    throw "Python 3 not found. Install it from https://www.python.org/downloads/ (check 'Add to PATH')."
}
$PyCmd = Find-Python

# ----- locate Claude Code ---------------------------------------------------
$Claude = (Get-Command claude -ErrorAction SilentlyContinue)
if (-not $Claude) {
    throw "Claude Code CLI not found. Install it with: npm i -g @anthropic-ai/claude-code"
}

# ----- ensure config.json exists (copy from the example on first run) -------
if (-not (Test-Path $Config)) {
    Copy-Item $ConfigExample $Config
    Write-Host "Created config.json from config.example.json - edit it to keep the models you have (and add your keys)." -ForegroundColor Yellow
}
$Cfg = Get-Content $Config -Raw | ConvertFrom-Json

# ----- resolve port + upstream from config.json (params/env override) -------
if ($Port -le 0) {
    $Port = 8141
    if ($Cfg.proxy.listen_port) { $Port = [int]$Cfg.proxy.listen_port }
}
if (-not $Upstream) {
    $Upstream = if ($Cfg.proxy.anthropic_upstream) { [string]$Cfg.proxy.anthropic_upstream } else { "https://api.anthropic.com" }
}

# ----- load optional ultracode.env into this process (for ${VAR} auth) ------
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

# 1M context window enablement: Claude Code only switches its context meter AND
# auto-compaction to the 1M window (and sends the context-1m beta) when the model
# id carries the [1m] suffix. The selector/config advertise bare ids (e.g.
# claude-opus-4-8), so without this the client sizes context at 200k -- the meter
# fills ~5x too fast and pins at 100% -- even though Opus 4.8 / Sonnet 4.6 serve
# 1M natively. We append [1m] to 1M-capable Claude base ids before launch.
# Disable with UC_FORCE_1M=0; override the capable set with UC_1M_MODELS.
function Add-Uc1m {
    param([string]$ModelId)
    if ($env:UC_FORCE_1M -eq "0") { return $ModelId }
    if ([string]::IsNullOrEmpty($ModelId)) { return $ModelId }
    if ($ModelId.Contains("[1m]")) { return $ModelId }
    $set = if ($env:UC_1M_MODELS) { $env:UC_1M_MODELS }
           else { "claude-opus-4-8,claude-opus-4-7,claude-opus-4-6,claude-sonnet-4-6,claude-opus" }
    foreach ($id in $set.Split(",")) {
        if ($ModelId -eq $id.Trim()) { return "${ModelId}[1m]" }
    }
    return $ModelId
}
$DefaultModel = Add-Uc1m "claude-opus-4-8"

@{
    ultracode = $true
    model     = $DefaultModel
    env       = @{
        ANTHROPIC_BASE_URL                         = $BaseUrl
        CLAUDE_CODE_WORKFLOWS                       = "1"
        CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY  = "1"
    }
} | ConvertTo-Json -Depth 5 | Set-Content -Path $Settings -Encoding utf8

# ----- proxy environment ----------------------------------------------------
$env:UC_CONFIG      = $Config
$env:UC_LISTEN_PORT = "$Port"
$env:UC_UPSTREAM    = $Upstream
$env:UC_LOG         = Join-Path $StateDir "ultracode_proxy.log"

# ----- shared-proxy lifecycle (reference-counted across sessions) -----------
# Several UltraCode sessions reuse one proxy on this port. Track live users with
# one marker file per launcher process so one session exiting cannot kill the
# proxy while another is still using it.
$RefDir   = Join-Path $StateDir "refs"
$PidFile  = Join-Path $StateDir "proxy.pid"
$OwnerRef = Join-Path $RefDir "$PID"

# Preserve the user-global model across the session. Claude Code persists an
# in-session /model pick (Enter in the picker) to settings.json as the `model`
# key (v2.1.153+), so picking a proxy-only id would become your global default
# and break a plain `claude` run outside the proxy. We snapshot that key before
# launch and restore it on exit (ref-count-safe). The JSON edit is done via
# Python (not ConvertTo-Json) so the rest of settings.json is left byte-for-key
# intact. Disable with UC_PRESERVE_GLOBAL_MODEL=0.
$CfgDir              = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
$GlobalSettings      = Join-Path $CfgDir "settings.json"
$SavedModelFile      = Join-Path $StateDir "saved_global_model.json"
$PreserveGlobalModel = ($env:UC_PRESERVE_GLOBAL_MODEL -ne "0")
$SnapPy = @'
import json,sys
src,dst=sys.argv[1],sys.argv[2]
try: s=json.load(open(src))
except Exception: s={}
json.dump({"had":"model" in s,"model":s.get("model")},open(dst,"w"))
'@
$RestorePy = @'
import json,sys
settings_f,saved_f=sys.argv[1],sys.argv[2]
try: saved=json.load(open(saved_f))
except Exception: saved={}
try: s=json.load(open(settings_f))
except Exception: s=None
if isinstance(s,dict):
    if saved.get("had"): s["model"]=saved.get("model")
    else: s.pop("model",None)
    f=open(settings_f,"w"); json.dump(s,f,indent=2); f.write("\n"); f.close()
'@

function Invoke-UcPy {
    param([string]$Code, [string[]]$Rest)
    $a = @()
    if ($PyCmd.Count -gt 1) { $a += $PyCmd[1..($PyCmd.Count-1)] }
    $a += @("-c", $Code) + $Rest
    & $PyCmd[0] @a 2>$null
}

function Save-GlobalModel {
    if (-not $PreserveGlobalModel) { return }
    # Clean start: refresh the snapshot. Other session live: keep theirs so we
    # never capture a mid-session pick as the "original".
    if ((Test-RefsActive) -and (Test-Path $SavedModelFile)) { return }
    try { Invoke-UcPy $SnapPy @($GlobalSettings, $SavedModelFile) } catch {}
}

function Restore-GlobalModel {
    if (-not $PreserveGlobalModel) { return }
    if (-not (Test-Path $SavedModelFile)) { return }
    if (Test-RefsActive) { return }   # other sessions live; last one out restores
    try { Invoke-UcPy $RestorePy @($GlobalSettings, $SavedModelFile) } catch {}
    Remove-Item $SavedModelFile -Force -ErrorAction SilentlyContinue
}

function Test-ProxyHealthy {
    try { return (Invoke-WebRequest -Uri "$BaseUrl/healthz" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }
    catch { return $false }
}

function Remove-DeadRefs {
    if (-not (Test-Path $RefDir)) { return }
    Get-ChildItem $RefDir -File -ErrorAction SilentlyContinue | ForEach-Object {
        $rpid = $_.Name
        if ($rpid -notmatch '^\d+$' -or -not (Get-Process -Id ([int]$rpid) -ErrorAction SilentlyContinue)) {
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-RefsActive {
    Remove-DeadRefs
    return ((Test-Path $RefDir) -and @(Get-ChildItem $RefDir -File -ErrorAction SilentlyContinue).Count -gt 0)
}

function Stop-ProxyIfLast {
    Remove-Item $OwnerRef -Force -ErrorAction SilentlyContinue
    Restore-GlobalModel
    if (Test-RefsActive) { return }
    if (Test-Path $PidFile) {
        $stopId = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($stopId) { Stop-Process -Id ([int]$stopId) -Force -ErrorAction SilentlyContinue }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

if ($Status) {
    if (-not (Test-ProxyHealthy)) {
        Write-Error "UltraCode proxy is not running on $BaseUrl. Start it with: .\windows\Start-UltraCode.ps1"
        exit 1
    }
    $health = Invoke-RestMethod -Uri "$BaseUrl/healthz" -TimeoutSec 3
    $ow = $health.orchestrator_worker
    Write-Host "UltraCode proxy: $BaseUrl"
    if ($ow.enabled) {
        Write-Host "Orchestrator/worker routing: on"
        Write-Host ("  Orchestrator: {0} ({1})" -f $ow.orchestrator.display_name, $ow.orchestrator.id)
        Write-Host ("  Worker:       {0} ({1})" -f $ow.worker.display_name, $ow.worker.id)
        if ($ow.worker_explicit) {
            Write-Host "  (worker set explicitly — plain /model picks change orchestrator only)"
        } elseif ($ow.same_model) {
            Write-Host "  (same model runs orchestrator and all workers)"
        }
    } else {
        Write-Host "Orchestrator/worker routing: off"
    }
    Write-Host "Live detail: curl -s $BaseUrl/healthz | python -m json.tool"
    exit 0
}

New-Item -ItemType Directory -Force -Path $RefDir | Out-Null
Save-GlobalModel
New-Item -ItemType File -Force -Path $OwnerRef | Out-Null

if (Test-ProxyHealthy) {
    Write-Host "Reusing the UltraCode proxy already running on $BaseUrl." -ForegroundColor Green
} else {
    Write-Host "Starting UltraCode proxy on $BaseUrl -> $Upstream ..."
    $pyArgs = @()
    if ($PyCmd.Count -gt 1) { $pyArgs += $PyCmd[1..($PyCmd.Count-1)] }
    $pyArgs += $Proxy
    $proc = Start-Process -FilePath $PyCmd[0] -ArgumentList $pyArgs -PassThru -WindowStyle Hidden
    Set-Content -Path $PidFile -Value $proc.Id -Encoding ascii

    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-ProxyHealthy) { $ready = $true; break }
    }
    if (-not $ready) {
        Write-Error "Proxy did not become healthy on port $Port. Log: $($env:UC_LOG)"
        if (Test-Path $env:UC_LOG) { Get-Content $env:UC_LOG -Tail 20 }
        Remove-Item $OwnerRef -Force -ErrorAction SilentlyContinue
        exit 1
    }
    Write-Host "Proxy healthy (pid $($proc.Id))." -ForegroundColor Green
}

# ----- seed Claude Code's gateway-models cache (first-launch visibility) -----
# Seed stock Claude + your configured models so real Claude and your picks all
# show on the very first /model open (before Claude Code re-fetches /v1/models).
$GwCache = Join-Path (Join-Path $CfgDir "cache") "gateway-models.json"
try {
    New-Item -ItemType Directory -Force -Path (Split-Path $GwCache) | Out-Null
    $health = Invoke-RestMethod -Uri "$BaseUrl/healthz" -TimeoutSec 2
    $models = [System.Collections.ArrayList]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($src in @($health.stock_models, $health.custom_models)) {
        foreach ($m in @($src)) {
            if ($m -and $m.id -and $seen.Add([string]$m.id)) {
                [void]$models.Add([ordered]@{ id = $m.id; display_name = $m.display_name })
            }
        }
    }
    $seed = [ordered]@{
        baseUrl   = $BaseUrl
        fetchedAt = [int64]([datetimeoffset](Get-Date)).ToUnixTimeMilliseconds()
        models    = @($models)
    }
    $seed | ConvertTo-Json -Depth 5 | Set-Content -Path $GwCache -Encoding utf8
    Write-Host "Seeded gateway-models cache ($(@($models).Count) models)."
} catch {
    Write-Host "WARN: could not seed gateway-models cache: $_" -ForegroundColor Yellow
}

if ($ProxyOnly) {
    Remove-Item $OwnerRef -Force -ErrorAction SilentlyContinue
    Restore-GlobalModel
    $shownPid = if (Test-Path $PidFile) { Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1 } else { "<pid>" }
    Write-Host ""
    Write-Host "Proxy running. Connect Claude Code with:"
    Write-Host "  `$env:ANTHROPIC_BASE_URL='$BaseUrl'"
    Write-Host "  claude --settings `"$Settings`""
    Write-Host "Stop the proxy: Stop-Process -Id $shownPid"
    exit 0
}

# ----- launch Claude Code through the proxy ---------------------------------
$env:ANTHROPIC_BASE_URL = $BaseUrl
$env:CLAUDE_CODE_WORKFLOWS = "1"
$env:CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = "1"

$SelectedModel = ""
$Selector = Join-Path $RepoRoot "scripts\ultracode_selector.py"
if (($env:UC_SELECTOR -ne "0") -and (Test-Path $Selector)) {
    try {
        $env:UC_PROXY = $BaseUrl
        $selArgs = @()
        if ($PyCmd.Count -gt 1) { $selArgs += $PyCmd[1..($PyCmd.Count-1)] }
        $selArgs += $Selector
        $SelectedModel = (& $PyCmd[0] @selArgs | Select-Object -Last 1)
        if ($LASTEXITCODE -eq 0 -and $SelectedModel) {
            Write-Host "Selected orchestrator: $SelectedModel" -ForegroundColor Green
        } elseif ($LASTEXITCODE -eq 1) {
            Write-Host "Selector cancelled; launching with default model." -ForegroundColor Yellow
            $SelectedModel = ""
        } else {
            Write-Host "Selector unavailable; launching with default model." -ForegroundColor Yellow
            $SelectedModel = ""
        }
    } catch {
        Write-Host "Selector unavailable; launching with default model: $_" -ForegroundColor Yellow
        $SelectedModel = ""
    }
    # Upgrade a 1M-capable Claude pick to its [1m] variant so the client uses the
    # full 1M context window (meter + auto-compaction), not the 200k default.
    $SelectedModel = Add-Uc1m $SelectedModel
    if ($SelectedModel) { Write-Host "Orchestrator model id: $SelectedModel" -ForegroundColor Green }
}

$HasModelArg = $false
foreach ($a in $args) {
    if ($a -eq "--model" -or $a.StartsWith("--model=")) { $HasModelArg = $true }
}

Write-Host "Launching Claude Code (UltraCode). Use /model anytime to change backend." -ForegroundColor Green
try {
    if ($SelectedModel -and -not $HasModelArg) {
        & $Claude.Source --settings "$Settings" --model "$SelectedModel" @args
    } else {
        & $Claude.Source --settings "$Settings" @args
    }
} finally {
    Write-Host "Claude exited. Releasing the UltraCode proxy."
    Stop-ProxyIfLast
}
