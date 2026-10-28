# Ragnarok - run the app as ONE process (API + web UI on a single port). Windows.
#
# Usage:  .\serve.ps1 [server|local]      (serve.bat is the double-click wrapper)
#   server (default) -> binds 0.0.0.0   : any machine on your LAN (see warning)
#   local            -> binds 127.0.0.1 : only this machine
#
# Deployment / "just use it" launcher (contrast run.* = DEV mode). One uvicorn
# worker serves the committed web build at .\build together with the API; no
# --reload, single worker (SQLite stores are single-writer). PowerShell 5.1 OK.
#
# Output goes to the console AND to logs\serve.log (next to this script).
# pandapower needs nothing here: the backend builds its own environment in the
# background on the first pandapower import (backend\pypsa\network\pandapower_env.py).
param([ValidateSet('local','server')][string]$Mode = 'server')

# Native commands (pip, python, npm) write progress to stderr. Under 'Stop' that
# becomes a terminating error, so each native call is checked via $LASTEXITCODE.
$ErrorActionPreference = 'Continue'

# A double-clicked .bat or .ps1 starts wherever the shell is; never rely on that.
Set-Location -LiteralPath $PSScriptRoot
$Root = $PSScriptRoot

$LogDir      = Join-Path $Root 'logs'
$LogFile     = Join-Path $LogDir 'serve.log'
$BindHost    = if ($Mode -eq 'server') { '0.0.0.0' } else { '127.0.0.1' }
$Frontend    = Join-Path $Root 'frontend\Ragnarok_default'
$VenvDir     = Join-Path $Root '.venv-pypsa'
$PythonExe   = Join-Path $VenvDir 'Scripts\python.exe'
$ReqFile     = Join-Path $Root 'backend\requirements.txt'
$ReqHashFile = Join-Path $VenvDir '.req_hash'
$McpReqFile  = Join-Path $Root 'backend\mcp\requirements-mcp.txt'
$Port        = if ($env:RAGNAROK_PORT) { $env:RAGNAROK_PORT } else { '8000' }
$McpPort     = if ($env:RAGNAROK_MCP_PORT) { $env:RAGNAROK_MCP_PORT } else { '8765' }
$script:McpProc = $null
$exitCode    = 0

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
try { Start-Transcript -Path $LogFile -Append -Force | Out-Null } catch { }

# Free a TCP port held by a stale previous run, so a restart does not fail to bind.
function Free-Port([int]$p) {
    try {
        Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { if ($_ -and $_ -ne 0) { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }
    } catch { }
}

# Find a real Python 3.11+. Skips the Microsoft Store alias stub (it is in WindowsApps
# and prints nothing useful), then tries the py launcher, PATH names, and the
# default per-user install folders. Returns @{Exe; Pre} or $null.
function Find-Python {
    $candidates = @()
    foreach ($v in @('3.13', '3.12', '3.11')) { $candidates += @{ Exe = 'py'; Pre = @("-$v") } }
    $candidates += @{ Exe = 'python'; Pre = @() }
    $candidates += @{ Exe = 'python3'; Pre = @() }
    $installRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path $installRoot) {
        foreach ($dir in (Get-ChildItem -LiteralPath $installRoot -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
            $candidates += @{ Exe = (Join-Path $dir.FullName 'python.exe'); Pre = @() }
        }
    }
    $probe = 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    foreach ($c in $candidates) {
        $cmd = Get-Command $c.Exe -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($cmd.Source -and $cmd.Source -like '*\WindowsApps\*') { continue }
        & $c.Exe @($c.Pre) -c $probe *> $null
        if ($LASTEXITCODE -eq 0) { return $c }
    }
    return $null
}

function Find-Npm {
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command npm -ErrorAction SilentlyContinue }
    if ($cmd) { return $cmd.Source }
    return $null
}

function Main {
    Write-Host "Ragnarok serve ($Mode) started $(Get-Date -Format s) in $Root"

    # -- Python env ----------------------------------------------------------------
    # Rebuild a broken venv or one on Python < 3.11. Removing it also drops .req_hash.
    if (Test-Path $PythonExe) {
        & $PythonExe -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Rebuilding virtual environment (Python < 3.11 or broken)...'
            Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not (Test-Path $PythonExe)) {
        $Py = Find-Python
        if (-not $Py) {
            throw 'Python 3.11 or newer was not found. Install Python 3.12 from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.'
        }
        Write-Host "Creating virtual environment with $($Py.Exe) $($Py.Pre -join ' ')..."
        & $Py.Exe @($Py.Pre) -m venv $VenvDir
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $PythonExe)) {
            throw "Could not create the virtual environment in $VenvDir."
        }
    }

    # -- Backend dependencies: reinstall when requirements.txt changed ----------------
    # The stamp is the MD5 of requirements.txt. A changed hash, a missing stamp, or an
    # environment that cannot import uvicorn/fastapi all trigger pip install -r.
    $ReqHash   = (Get-FileHash -LiteralPath $ReqFile -Algorithm MD5).Hash
    $StoredHash = if (Test-Path $ReqHashFile) { (Get-Content -LiteralPath $ReqHashFile -Raw).Trim() } else { '' }
    & $PythonExe -c 'import uvicorn, fastapi' *> $null
    $DepsOk = ($LASTEXITCODE -eq 0)
    if ($ReqHash -ne $StoredHash -or -not $DepsOk) {
        if ($ReqHash -ne $StoredHash -and $StoredHash -ne '') {
            Write-Host 'backend\requirements.txt changed since the last install - updating the backend dependencies...'
        } else {
            Write-Host 'Installing backend dependencies (the first run takes several minutes)...'
        }
        # Drop the stamp first: an interrupted or failed install must not look up to date.
        Remove-Item -LiteralPath $ReqHashFile -Force -ErrorAction SilentlyContinue
        & $PythonExe -m pip install --disable-pip-version-check --quiet --upgrade pip
        & $PythonExe -m pip install -r $ReqFile
        if ($LASTEXITCODE -ne 0) {
            throw 'Backend dependency install failed - the pip output is in logs\serve.log. Use Python 3.12 (python.org) or install the Visual C++ Build Tools, then run this again.'
        }
        Set-Content -LiteralPath $ReqHashFile -Value $ReqHash -Encoding ASCII
    }

    # -- Web build (committed at .\build; rebuilt only when missing and npm exists) --
    # A failed build does not stop the app: the API still starts, without the GUI.
    $Dist = if ($env:RAGNAROK_FRONTEND_DIST) { $env:RAGNAROK_FRONTEND_DIST } else { Join-Path $Root 'build' }
    if (-not (Test-Path $Dist)) {
        $NpmExe = Find-Npm
        if ($NpmExe) {
            Write-Host 'No web build yet - building it now (one-time, takes a few minutes)...'
            Push-Location $Frontend
            try {
                if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) { & $NpmExe install --no-audit --no-fund }
                $env:GENERATE_SOURCEMAP = 'false'
                & $NpmExe run build
                $buildOk = ($LASTEXITCODE -eq 0)
            } finally { Pop-Location }
            if ($buildOk -and $Dist -eq (Join-Path $Root 'build')) {
                Copy-Item -Recurse -Force (Join-Path $Frontend 'build') $Dist
            } elseif (-not $buildOk) {
                Write-Host 'WARNING: the web build failed - starting the API without the GUI (details in logs\serve.log).'
            }
        } else {
            Write-Host "NOTE: no web build at $Dist and npm was not found - starting the API without the GUI."
            Write-Host '      To get the GUI: install Node.js from https://nodejs.org and run this again.'
        }
    }
    $env:RAGNAROK_FRONTEND_DIST = $Dist

    # -- MCP server (agent bridge) - its own port, so remote agents connect by URL --
    # Set RAGNAROK_MCP=off to skip it. Failure to start it does not stop the app.
    if ($env:RAGNAROK_MCP -ne 'off') {
        & $PythonExe -c 'import mcp' *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Installing MCP server dependencies...'
            & $PythonExe -m pip install --disable-pip-version-check --quiet -r $McpReqFile
        }
        & $PythonExe -c 'import mcp' *> $null
        if ($LASTEXITCODE -eq 0) {
            Free-Port ([int]$McpPort)
            $env:RAGNAROK_MCP_TRANSPORT = 'streamable-http'
            $env:RAGNAROK_MCP_HOST      = $BindHost
            $env:RAGNAROK_MCP_PORT      = $McpPort
            $env:RAGNAROK_API_BASE      = "http://127.0.0.1:$Port"
            $env:PYTHONPATH             = $Root
            $script:McpProc = Start-Process -FilePath $PythonExe -ArgumentList @('-m', 'backend.mcp') -WorkingDirectory $Root `
                -PassThru -NoNewWindow -RedirectStandardOutput (Join-Path $LogDir 'mcp.log') -RedirectStandardError (Join-Path $LogDir 'mcp.err.log')
        } else {
            Write-Host 'NOTE: MCP dependencies unavailable - starting the app without the agent bridge.'
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
            if ($script:McpProc) { Write-Host "  mcp:  http://$($ip.IPAddress):$McpPort/mcp   (point LM Studio / agents here)" }
        }
        Write-Host "  app:  http://$($env:COMPUTERNAME).local:$Port"
        Write-Host ''
        Write-Host 'WARNING: no authentication - trusted networks only (plugin install runs'
        Write-Host 'uploaded Python by design; the mcp port drives the model too). Do not expose'
        $fwPorts = if ($script:McpProc) { "$Port and $McpPort" } else { "$Port" }
        Write-Host "to the internet. Allow inbound TCP $fwPorts on the firewall."
    } else {
        Write-Host 'Local mode - open on this machine:'
        Write-Host "  app:  http://127.0.0.1:$Port"
        if ($script:McpProc) { Write-Host "  mcp:  http://127.0.0.1:$McpPort/mcp" }
    }
    Write-Host ''

    # -- Run the server in the foreground (Ctrl+C or closing the window stops it) ----
    Free-Port ([int]$Port)
    $env:PYTHONUNBUFFERED = '1'
    & $PythonExe -m uvicorn backend.app.main:app --host $BindHost --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "The server stopped with exit code $LASTEXITCODE. Port $Port may be in use by another program, or the app failed to start (see the messages above)."
    }
}

try {
    Main
} catch {
    $exitCode = 1
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Full log: $LogFile"
} finally {
    if ($script:McpProc -and -not $script:McpProc.HasExited) { Stop-Process -Id $script:McpProc.Id -Force -ErrorAction SilentlyContinue }
    Write-Host ''
    Write-Host "Ragnarok has stopped (exit code $exitCode). Log: $LogFile"
    try { Stop-Transcript | Out-Null } catch { }
}
exit $exitCode
