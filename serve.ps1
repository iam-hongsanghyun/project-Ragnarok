# Ragnarok - run the app as ONE process (API + web UI on a single port). Windows.
#
# Usage:  .\serve.ps1 [server|local]
#   server (default) -> binds 0.0.0.0   : any machine on your LAN (see warning)
#   local            -> binds 127.0.0.1 : only this machine
#
# Deployment / "just use it" launcher (contrast run.* = DEV mode). One uvicorn
# worker serves the committed web build at .\build together with the API; no
# --reload, single worker (SQLite stores are single-writer). PowerShell 5.1 OK.
param([ValidateSet('local','server')][string]$Mode = 'server')

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$BindHost  = if ($Mode -eq 'server') { '0.0.0.0' } else { '127.0.0.1' }
$Frontend  = Join-Path $PSScriptRoot 'frontend\Ragnarok_default'
$VenvDir   = Join-Path $PSScriptRoot '.venv-pypsa'
$PythonExe = Join-Path $VenvDir 'Scripts\python.exe'
$PipExe    = Join-Path $VenvDir 'Scripts\pip.exe'
$Port      = if ($env:RAGNAROK_PORT) { $env:RAGNAROK_PORT } else { '8000' }

function Die([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# Free a TCP port held by a stale previous run, so a restart doesn't fail to bind.
function Free-Port([int]$p) {
    try {
        Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    } catch {}
}

# -- Python env ------------------------------------------------------------------
if (-not (Test-Path $PythonExe)) {
    $Python = $null
    foreach ($candidate in @('python', 'py', 'python3')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $Python = $candidate; break }
        }
    }
    if (-not $Python) { Die 'Python 3.11+ is required: https://www.python.org/downloads/' }
    Write-Host 'Creating Python virtual environment...'
    & $Python -m venv $VenvDir
}

$ReqFile     = Join-Path $PSScriptRoot 'backend\requirements.txt'
$ReqHashFile = Join-Path $VenvDir '.req_hash'
$ReqHash     = (Get-FileHash $ReqFile -Algorithm MD5).Hash
$StoredHash  = if (Test-Path $ReqHashFile) { (Get-Content $ReqHashFile -Raw).Trim() } else { '' }

# Verify the venv actually imports the core deps, and (re)install if not. A
# matching .req_hash is not enough: a prior install may have failed, or the venv
# may have been copied from another machine. We drop ErrorActionPreference to
# 'Continue' around the native calls: under the script's global 'Stop', Python
# or pip writing to stderr (a missing-module traceback, a pip warning) is
# promoted to a TERMINATING error and would kill the script here — we check
# $LASTEXITCODE explicitly instead.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $PythonExe -c "import uvicorn, fastapi" 2>&1 | Out-Null
$DepsOk = ($LASTEXITCODE -eq 0)
if ($ReqHash.Trim() -ne $StoredHash -or -not $DepsOk) {
    Write-Host 'Installing backend dependencies...'
    & $PipExe install --upgrade pip --quiet
    & $PipExe install -r $ReqFile
    $pipCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    if ($pipCode -ne 0) { Die 'Backend dependency install failed - see the pip error above. Fix it (e.g. use Python 3.11/3.12, or install build tools) and re-run.' }
    Set-Content -Path $ReqHashFile -Value $ReqHash
} else {
    $ErrorActionPreference = $prevEAP
}

# -- Web build (committed at .\build; rebuild only if missing + npm present) ------
$Dist = if ($env:RAGNAROK_FRONTEND_DIST) { $env:RAGNAROK_FRONTEND_DIST } else { Join-Path $PSScriptRoot 'build' }
if (-not (Test-Path $Dist)) {
    $Npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($Npm) {
        Write-Host 'No web build yet - building it now (one-time)...'
        Push-Location $Frontend
        if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) { npm install --no-audit --no-fund }
        $env:GENERATE_SOURCEMAP = 'false'; npm run build
        if ($LASTEXITCODE -ne 0) { Pop-Location; Die 'Web build failed.' }
        Pop-Location
        if ($Dist -eq (Join-Path $PSScriptRoot 'build')) { Copy-Item -Recurse (Join-Path $Frontend 'build') $Dist }
    } else {
        Write-Host "NOTE: no web build at $Dist and npm not found - starting API-only."
    }
}
$env:RAGNAROK_FRONTEND_DIST = $Dist

# -- MCP server (Bifrost) - same-box HTTP bridge on its own port, so remote
# agents (LM Studio, Claude Desktop, ...) connect by URL with NOTHING installed
# client-side. Set env RAGNAROK_MCP=off to skip it. -----------------------------
$McpPort = if ($env:RAGNAROK_MCP_PORT) { $env:RAGNAROK_MCP_PORT } else { '8765' }
$McpProc = $null
if (($env:RAGNAROK_MCP -ne 'off')) {
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & $PythonExe -c "import mcp" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing MCP server dependencies...'
        & $PipExe install -r (Join-Path $PSScriptRoot 'backend\mcp\requirements-mcp.txt') --quiet
    }
    & $PythonExe -c "import mcp" 2>&1 | Out-Null
    $McpOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prevEAP
    if ($McpOk) {
        $env:RAGNAROK_MCP_TRANSPORT = 'streamable-http'
        $env:RAGNAROK_MCP_HOST      = $BindHost
        $env:RAGNAROK_MCP_PORT      = $McpPort
        $env:RAGNAROK_API_BASE      = "http://127.0.0.1:$Port"
        $env:PYTHONPATH             = $PSScriptRoot
        Free-Port ([int]$McpPort)
        $McpProc = Start-Process -FilePath $PythonExe -ArgumentList '-m','backend.mcp' -PassThru -NoNewWindow
    } else {
        Write-Host 'NOTE: MCP deps unavailable - starting the app without the agent bridge.'
    }
}

# -- Announce URL(s) -------------------------------------------------------------
Write-Host ''
if ($Mode -eq 'server') {
    Write-Host 'Server mode - open from any machine on this network:'
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }
    foreach ($ip in $ips) {
        Write-Host "  app:  http://$($ip.IPAddress):$Port"
        if ($McpProc) { Write-Host "  mcp:  http://$($ip.IPAddress):$McpPort/mcp   (point LM Studio / agents here)" }
    }
    Write-Host "  app:  http://$($env:COMPUTERNAME).local:$Port"
    Write-Host ''
    Write-Host 'WARNING: no authentication - trusted networks only (plugin install runs'
    Write-Host "uploaded Python by design; the mcp port drives the model too). Do not expose"
    $fwPorts = if ($McpProc) { "$Port and $McpPort" } else { "$Port" }
    Write-Host "to the internet. Allow inbound TCP $fwPorts on the firewall."
} else {
    Write-Host 'Local mode - open on this machine:'
    Write-Host "  app:  http://127.0.0.1:$Port"
    if ($McpProc) { Write-Host "  mcp:  http://127.0.0.1:$McpPort/mcp" }
}
Write-Host ''

Free-Port ([int]$Port)
try {
    & $PythonExe -m uvicorn backend.app.main:app --host $BindHost --port $Port
} finally {
    if ($McpProc -and -not $McpProc.HasExited) { Stop-Process -Id $McpProc.Id -Force -ErrorAction SilentlyContinue }
}
