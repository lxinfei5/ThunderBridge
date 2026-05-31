<#
  doctor.ps1 -- ultracode-unlock health & config checker (Windows)

  Run this when something isn't working. It checks:
    - Python is available
    - config.json exists and is valid JSON
    - every model id starts with claude/anthropic and has a route
    - the proxy is reachable on its port (/healthz)
    - Claude Code env vars are pointed at the proxy

  Usage:  ./doctor.ps1
#>
$ErrorActionPreference = "Continue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

$ok = 0; $warn = 0; $fail = 0
function Pass($m){ Write-Host "  [PASS] $m" -ForegroundColor Green; $script:ok++ }
function Warn($m){ Write-Host "  [WARN] $m" -ForegroundColor Yellow; $script:warn++ }
function Fail($m){ Write-Host "  [FAIL] $m" -ForegroundColor Red; $script:fail++ }

Write-Host "ultracode-unlock doctor" -ForegroundColor Cyan
Write-Host "=======================" -ForegroundColor Cyan

# Python
$Python = $null
foreach ($cand in @((Join-Path $Here ".venv\Scripts\python.exe"), (Join-Path $Here "venv\Scripts\python.exe"))) {
    if (Test-Path $cand) { $Python = $cand; break }
}
if (-not $Python) { foreach ($n in @("python","py")) { $c = Get-Command $n -ErrorAction SilentlyContinue; if ($c){ $Python = $c.Source; break } } }
if ($Python) { Pass "Python found: $Python" } else { Fail "No Python interpreter (need 3.8+)." }

# config.json
$ConfigPath = Join-Path $Here "config.json"
$Port = 8141
$cfg = $null
if (-not (Test-Path $ConfigPath)) {
    Fail "config.json missing. Run ./start.ps1 once to create it from config.example.json."
} else {
    try {
        $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        Pass "config.json is valid JSON."
        if ($cfg.proxy -and $cfg.proxy.listen_port) { $Port = [int]$cfg.proxy.listen_port }
    } catch { Fail "config.json is not valid JSON: $_" }
}

# models + routes
if ($cfg -and $cfg.models) {
    foreach ($m in $cfg.models) {
        $id = $m.id
        if (-not ($id -match '^(claude|anthropic)')) {
            Fail "model id '$id' must start with 'claude' or 'anthropic' (Claude Code hides others)."
        } else {
            $route = $cfg.routes.$id
            if ($route) {
                if ($route.auth -match 'REPLACE_ME') { Warn "route '$id' still has a placeholder API key (auth contains REPLACE_ME)." }
                else { Pass "model '$id' -> $($route.type) @ $($route.upstream) (model=$($route.model))" }
            } else { Warn "model '$id' has no entry in 'routes' (will pass through to Anthropic)." }
        }
    }
} elseif ($cfg) { Warn "no models configured in config.json." }

# proxy reachable
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 4
    Pass "proxy reachable on http://127.0.0.1:$Port (effort=$($h.effort), max_tokens_floor=$($h.max_tokens_floor))"
} catch {
    Warn "proxy not reachable on port $Port. Start it with ./start.ps1 (or ./start.ps1 -NoClaude)."
}

# env vars
if ($env:ANTHROPIC_BASE_URL -eq "http://127.0.0.1:$Port") {
    Pass "ANTHROPIC_BASE_URL points at the proxy."
} else {
    Warn "ANTHROPIC_BASE_URL is '$($env:ANTHROPIC_BASE_URL)' (expected http://127.0.0.1:$Port). start.ps1 sets this for you."
}
if ($env:CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY) { Pass "gateway model discovery enabled." }
else { Warn "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY not set (needed for the custom /model menu)." }

Write-Host ""
Write-Host ("Summary: $ok pass, $warn warn, $fail fail") -ForegroundColor Cyan
if ($fail -gt 0) { exit 1 } else { exit 0 }
