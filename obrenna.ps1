# Obrenna dev process manager (native PowerShell - no Git Bash dependency).
#
# Usage:
#   .\obrenna.ps1 start      # start EVERYTHING: backend, frontend, Ollama,
#                            # codebase-agent, gateway (if present)
#   .\obrenna.ps1 stop       # stop EVERYTHING, Ollama included
#   .\obrenna.ps1 restart    # stop, then start
#   .\obrenna.ps1 status     # show what's currently running

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$AgentDir = Join-Path $Root "codebase-agent"
$LogDir = Join-Path $Root ".run"

# The gateway is a SEPARATE sibling repo (login + Cloudflare tunnel that
# publishes Obrenna at llm.alex-dyakin.com). Only needed for public access;
# local dev uses http://localhost:5173 directly.
$GatewayDir = if ($env:OBRENNA_GATEWAY_DIR) { $env:OBRENNA_GATEWAY_DIR } else { Join-Path (Split-Path $Root -Parent) "obrenna-gateway" }
$CaddyBin = if ($env:CADDY_BIN) { $env:CADDY_BIN } else { "$HOME\AppData\Local\caddy\caddy.exe" }
$CloudflaredBin = if ($env:CLOUDFLARED_BIN) { $env:CLOUDFLARED_BIN } else { "$HOME\AppData\Local\cloudflared\cloudflared.exe" }

$BackendPort = 8000
$FrontendPort = 5173
$OllamaPort = 11434
$AuthPort = 9100
$CaddyPort = 9080

function Test-PortListening($port) {
  [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Stop-ByPort($port) {
  # Kills the port's owning process AND any child it spawned (uvicorn
  # --reload forks a worker via multiprocessing; killing just the parent
  # orphans a worker that keeps the socket alive and keeps serving requests).
  $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -Expand OwningProcess -Unique
  foreach ($o in $owners) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$o" -ErrorAction SilentlyContinue |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $o -Force -ErrorAction SilentlyContinue
  }
}

function Test-AgentRunning {
  [bool](Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'codebase_agent\.main' })
}

function Stop-Agent {
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'codebase_agent\.main' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Test-CloudflaredRunning {
  [bool](Get-Process cloudflared -ErrorAction SilentlyContinue)
}

function Sweep-Stragglers {
  # Belt-and-suspenders pass, run at the end of every `stop`. Stop-ByPort
  # only catches processes currently bound to a tracked port (plus their
  # children); it misses a second instance that lost the bind race and is
  # sitting idle on no port at all. This matches by command-line signature
  # instead, so it finds those regardless of port state, then sweeps each
  # match's own children too (same reason as above).
  $victims = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -eq 'node.exe'   -and $_.CommandLine -like '*vite*') -or
    ($_.Name -eq 'python.exe' -and $_.CommandLine -like "*uvicorn main:app*port $BackendPort*") -or
    ($_.Name -eq 'python.exe' -and $_.CommandLine -like "*uvicorn main:app*port $AuthPort*") -or
    ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*codebase_agent.main*') -or
    $_.Name -in @('caddy.exe', 'cloudflared.exe')
  }
  foreach ($v in $victims) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$($v.ProcessId)" -ErrorAction SilentlyContinue |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $v.ProcessId -Force -ErrorAction SilentlyContinue
  }
}

function Start-Backend {
  if (Test-PortListening $BackendPort) {
    Write-Host "Backend already listening on :$BackendPort, skipping."
    return
  }
  Write-Host "Starting backend on :$BackendPort..."
  Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "main:app", "--reload", "--port", "$BackendPort" `
    -WorkingDirectory $BackendDir -WindowStyle Hidden `
    -RedirectStandardOutput "$LogDir\backend.log" -RedirectStandardError "$LogDir\backend.err.log"
}

function Start-Frontend {
  if (Test-PortListening $FrontendPort) {
    Write-Host "Frontend already listening on :$FrontendPort, skipping."
    return
  }
  Write-Host "Starting frontend on :$FrontendPort..."
  Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run dev" `
    -WorkingDirectory $FrontendDir -WindowStyle Hidden `
    -RedirectStandardOutput "$LogDir\frontend.log" -RedirectStandardError "$LogDir\frontend.err.log"
}

function Start-Agent {
  if (Test-AgentRunning) {
    Write-Host "Codebase-agent already running, skipping."
    return
  }
  Write-Host "Starting codebase-agent (approve the device in Obrenna Settings)..."
  Start-Process -FilePath "python" -ArgumentList "-m", "codebase_agent.main", "--server", "http://localhost:$BackendPort" `
    -WorkingDirectory $AgentDir -WindowStyle Hidden `
    -RedirectStandardOutput "$LogDir\agent.log" -RedirectStandardError "$LogDir\agent.err.log"
}

function Start-Ollama {
  if (Test-PortListening $OllamaPort) {
    Write-Host "Ollama already running on :$OllamaPort, skipping."
    return
  }
  if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "ollama CLI not found on PATH - skipping (start it manually)."
    return
  }
  Write-Host "Starting Ollama on :$OllamaPort..."
  Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden `
    -RedirectStandardOutput "$LogDir\ollama.log" -RedirectStandardError "$LogDir\ollama.err.log"
}

function Stop-Gateway {
  Write-Host "Stopping gateway (auth :$AuthPort, Caddy :$CaddyPort, cloudflared)..."
  Stop-ByPort $AuthPort
  Stop-ByPort $CaddyPort
  Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

function Start-Gateway {
  if (-not (Test-Path $GatewayDir)) {
    Write-Host "Gateway repo not found at $GatewayDir - skipping (set OBRENNA_GATEWAY_DIR to override)."
    return
  }
  $authPy = Join-Path $GatewayDir ".venv\Scripts\python.exe"
  if (-not (Test-Path $authPy)) { $authPy = "python" }

  if (-not (Test-PortListening $BackendPort) -or -not (Test-PortListening $FrontendPort)) {
    Write-Host "  (note: the app :$BackendPort/:$FrontendPort isn't fully up yet - Caddy will 502 until it is.)"
  }

  if (Test-PortListening $AuthPort) {
    Write-Host "Auth service already on :$AuthPort, skipping."
  } else {
    Write-Host "Starting gateway auth service on :$AuthPort..."
    Start-Process -FilePath $authPy -ArgumentList "-m", "uvicorn", "main:app", "--port", "$AuthPort", "--app-dir", "auth_service" `
      -WorkingDirectory $GatewayDir -WindowStyle Hidden `
      -RedirectStandardOutput "$LogDir\gateway-auth.log" -RedirectStandardError "$LogDir\gateway-auth.err.log"
  }

  if (Test-PortListening $CaddyPort) {
    Write-Host "Caddy already on :$CaddyPort, skipping."
  } elseif (Test-Path $CaddyBin) {
    Write-Host "Starting Caddy on :$CaddyPort..."
    Start-Process -FilePath $CaddyBin -ArgumentList "run", "--config", "Caddyfile" `
      -WorkingDirectory $GatewayDir -WindowStyle Hidden `
      -RedirectStandardOutput "$LogDir\gateway-caddy.log" -RedirectStandardError "$LogDir\gateway-caddy.err.log"
  } else {
    Write-Host "Caddy binary not found at $CaddyBin - skipping (set CADDY_BIN to override)."
  }

  if (Test-CloudflaredRunning) {
    Write-Host "cloudflared already running, skipping."
  } elseif (Test-Path $CloudflaredBin) {
    Write-Host "Starting cloudflared tunnel (publishes llm.alex-dyakin.com)..."
    Start-Process -FilePath $CloudflaredBin -ArgumentList "tunnel", "--config", "cloudflared-config.yml", "run" `
      -WorkingDirectory $GatewayDir -WindowStyle Hidden `
      -RedirectStandardOutput "$LogDir\gateway-cloudflared.log" -RedirectStandardError "$LogDir\gateway-cloudflared.err.log"
  } else {
    Write-Host "cloudflared binary not found at $CloudflaredBin - skipping (set CLOUDFLARED_BIN to override)."
  }
}

function Get-DuplicateWarnings {
  # Catches exactly the failure mode that took the app down once already:
  # more than one process quietly claiming the same role (e.g. two backend
  # instances fighting over :8000). This can't happen from `start` alone
  # (it checks the port first) - it happens when something starts a
  # component OUTSIDE this script. Surface it loudly instead of letting it
  # sit for days.
  $roles = [ordered]@{
    "backend (uvicorn :$BackendPort)"   = { $_.Name -eq 'python.exe' -and $_.CommandLine -like "*uvicorn main:app*port $BackendPort*" }
    "frontend (vite)"                   = { $_.Name -eq 'node.exe'   -and $_.CommandLine -like '*vite*' }
    "codebase-agent"                    = { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*codebase_agent.main*' }
    "gateway auth (uvicorn :$AuthPort)" = { $_.Name -eq 'python.exe' -and $_.CommandLine -like "*uvicorn main:app*port $AuthPort*" }
  }
  $all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
  $found = $false
  foreach ($role in $roles.Keys) {
    $matches = $all | Where-Object $roles[$role]
    # A --reload fork-child (or any process launched via an intermediate
    # shim) can share an identical command line with its own parent. Only
    # count a match if its OWN parent isn't also a match, so such pairs
    # collapse to one before we decide it's a duplicate.
    $matchIds = $matches.ProcessId
    $roots = $matches | Where-Object { $matchIds -notcontains $_.ParentProcessId }
    if ($roots.Count -gt 1) {
      $found = $true
      Write-Host "WARNING: $($roots.Count) instances of '$role' running at once (PIDs: $(($roots.ProcessId) -join ', ')) - run '.\obrenna.ps1 stop' then 'start' to fix."
    }
  }
  if (-not $found) { Write-Host "No duplicates detected." }
}

function Invoke-Start {
  New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
  Start-Backend
  Start-Frontend
  Start-Ollama
  Start-Agent
  Start-Gateway
  Write-Host ""
  Write-Host "Frontend: http://localhost:$FrontendPort"
  Write-Host "Backend:  http://localhost:$BackendPort/docs"
  Write-Host "Ollama:   http://localhost:$OllamaPort"
  Write-Host "Logs:     $LogDir\*.log"
}

function Invoke-Stop {
  Write-Host "Stopping backend (:$BackendPort) and frontend (:$FrontendPort)..."
  Stop-ByPort $BackendPort
  Stop-ByPort $FrontendPort
  Write-Host "Stopping codebase-agent..."
  Stop-Agent
  Stop-Gateway
  Write-Host "Stopping Ollama (server + tray)..."
  Get-Process ollama, 'ollama app' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Sweep-Stragglers
  Write-Host "Stopped."
}

function Invoke-Restart {
  Invoke-Stop
  Start-Sleep -Seconds 2
  Invoke-Start
}

function Invoke-Status {
  Write-Host "Listening ports:"
  Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $BackendPort, $FrontendPort, $OllamaPort, $AuthPort, $CaddyPort } |
    ForEach-Object {
      $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
      "{0,-6} PID {1,-6} {2}" -f $_.LocalPort, $_.OwningProcess, $p.ProcessName
    } | Sort-Object -Unique

  Write-Host ""
  Write-Host "Codebase-agent:"
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'codebase_agent\.main' } |
    Select-Object ProcessId, CommandLine | Format-Table -AutoSize

  Write-Host "Gateway tunnel (cloudflared):"
  $c = Get-Process cloudflared -ErrorAction SilentlyContinue
  if ($c) { $c | Select-Object Id, ProcessName | Format-Table -AutoSize } else { Write-Host "  (not running)" }

  Write-Host ""
  Get-DuplicateWarnings
}

function Show-Usage {
  Write-Host "Usage: .\obrenna.ps1 {start|stop|restart|status}"
  Write-Host "  start    everything: backend, frontend, Ollama, codebase-agent, gateway (if present)"
  Write-Host "  stop     everything, Ollama included"
  Write-Host "  restart  stop then start"
  Write-Host "  status   show what's currently listening/running"
}

switch ($args[0]) {
  "start"   { Invoke-Start }
  "stop"    { Invoke-Stop }
  "restart" { Invoke-Restart }
  "status"  { Invoke-Status }
  default   { Show-Usage }
}
