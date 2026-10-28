# Ragnarok - Windows launcher, DEV mode (PowerShell). Called by run.bat.
# Live reload: backend on 127.0.0.1:8000 (uvicorn --reload), frontend dev server on :3000.
#
# Output: the launcher transcript is logs\run.log; the backend's own output is
# logs\backend.log (stdout) and logs\backend.err.log (stderr).
# pandapower needs nothing here: the backend builds its own environment in the
# background on the first pandapower import (backend\pypsa\network\pandapower_env.py).
#
# You can also right-click this file and choose "Run with PowerShell".

# Native commands (pip, python, npm) write progress to stderr. Under 'Stop' that
# becomes a terminating error, so each native call is checked via $LASTEXITCODE.
$ErrorActionPreference = 'Continue'

# A double-clicked .bat or .ps1 starts wherever the shell is; never rely on that.
Set-Location -LiteralPath $PSScriptRoot
$Root = $PSScriptRoot

$LogDir      = Join-Path $Root 'logs'
$LogFile     = Join-Path $LogDir 'run.log'
$BackendLog  = Join-Path $LogDir 'backend.log'
$BackendErr  = Join-Path $LogDir 'backend.err.log'
$VenvDir     = Join-Path $Root '.venv-pypsa'
$PythonExe   = Join-Path $VenvDir 'Scripts\python.exe'
$ReqFile     = Join-Path $Root 'backend\requirements.txt'
$ReqHashFile = Join-Path $VenvDir '.req_hash'
# Frontend lives in its own package. The npm project root is here, not the repo root.
$FrontendDir = Join-Path $Root 'frontend\Ragnarok_default'
$exitCode    = 0
$script:Backend = $null
$script:Plugins = @()

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
try { Start-Transcript -Path $LogFile -Append -Force | Out-Null } catch { }

# Find a real Python 3.11+. Skips the Microsoft Store alias stub (it is in WindowsApps),
# then tries the py launcher, PATH names, and the default per-user install folders.
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

# Free a TCP port held by a stale previous run, so a restart does not fail to bind.
function Free-Port([int]$port) {
    try {
        $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($p in $pids) {
            if ($p -and $p -ne 0) {
                Write-Host "Port $port busy - stopping PID $p"
                Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            }
        }
    } catch { }
}

# Registered plugin servers (plugins.env): "<server dir>|<run command>" per line.
# Plugins never talk to the backend; this only starts the local servers the frontend
# plugins connect to. A plugin that fails to start is logged and skipped.
function Start-PluginServers {
    $envFile = if ($env:RAGNAROK_PLUGINS_ENV) { $env:RAGNAROK_PLUGINS_ENV } else { Join-Path $Root 'plugins.env' }
    $procs = @()
    if (-not (Test-Path $envFile)) { return $procs }
    foreach ($line in Get-Content -LiteralPath $envFile) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $bar = $t.IndexOf('|')
        if ($bar -lt 0) { continue }
        $pdir = $t.Substring(0, $bar).Trim()
        $pcmd = $t.Substring($bar + 1).Trim()
        if ($pdir -eq '' -or $pcmd -eq '') { continue }
        if (-not (Test-Path $pdir)) {
            Write-Host "Skip plugin server (directory not found): $pdir"
            continue
        }
        # Free this plugin's port first so a stale server cannot hold it.
        $pport = $null
        if ($pcmd -match '(?:--port|-p)[\s=]+(\d+)') { $pport = [int]$Matches[1] }
        elseif ($pcmd -match ':(\d{2,5})\b') { $pport = [int]$Matches[1] }
        if ($pport) { Free-Port $pport }

        # Run in the plugin's own environment: its .venv if present, else the Ragnarok venv.
        $parts = $pcmd -split '\s+'
        $exe = $parts[0]
        $rest = if ($parts.Count -gt 1) { $parts[1..($parts.Count - 1)] } else { @() }
        if ($exe -ieq 'python' -or $exe -ieq 'python3') {
            $pluginPy = Join-Path $pdir '.venv\Scripts\python.exe'
            $exe = if (Test-Path $pluginPy) { $pluginPy } else { $PythonExe }
        }
        Write-Host "Starting plugin server: $pdir -> $pcmd"
        try {
            $p = Start-Process -FilePath $exe -ArgumentList $rest -WorkingDirectory $pdir -PassThru -NoNewWindow -ErrorAction Stop
            $procs += $p
        } catch {
            Write-Host "WARNING: failed to start plugin server $pdir ($($_.Exception.Message)) - continuing without it."
        }
    }
    return $procs
}

function Main {
    Write-Host "Ragnarok dev launcher started $(Get-Date -Format s) in $Root"

    # -- Prerequisites ----------------------------------------------------------------
    $NpmExe = Find-Npm
    if (-not $NpmExe) { throw 'npm was not found. Install Node.js (it includes npm) from https://nodejs.org, then run this again.' }
    $Py = Find-Python
    if (-not $Py -and -not (Test-Path $PythonExe)) {
        throw 'Python 3.11 or newer was not found. Install Python 3.12 from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.'
    }

    # -- Python env ----------------------------------------------------------------
    if (Test-Path $PythonExe) {
        & $PythonExe -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Rebuilding virtual environment (Python < 3.11 or broken)...'
            Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not (Test-Path $PythonExe)) {
        Write-Host "Creating virtual environment with $($Py.Exe) $($Py.Pre -join ' ')..."
        & $Py.Exe @($Py.Pre) -m venv $VenvDir
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $PythonExe)) {
            throw "Could not create the virtual environment in $VenvDir."
        }
    }

    # -- Backend dependencies: reinstall when requirements.txt changed -----------------
    $env:MPLCONFIGDIR = Join-Path $Root '.matplotlib'
    New-Item -ItemType Directory -Force -Path $env:MPLCONFIGDIR | Out-Null
    $ReqHash    = (Get-FileHash -LiteralPath $ReqFile -Algorithm MD5).Hash
    $StoredHash = if (Test-Path $ReqHashFile) { (Get-Content -LiteralPath $ReqHashFile -Raw).Trim() } else { '' }
    & $PythonExe -c 'import uvicorn, fastapi' *> $null
    $DepsOk = ($LASTEXITCODE -eq 0)
    if ($ReqHash -ne $StoredHash -or -not $DepsOk) {
        if ($ReqHash -ne $StoredHash -and $StoredHash -ne '') {
            Write-Host 'backend\requirements.txt changed since the last install - updating the backend dependencies...'
        } else {
            Write-Host 'Installing backend dependencies (the first run takes several minutes)...'
        }
        Remove-Item -LiteralPath $ReqHashFile -Force -ErrorAction SilentlyContinue
        & $PythonExe -m pip install --disable-pip-version-check --quiet --upgrade pip
        & $PythonExe -m pip install -r $ReqFile
        if ($LASTEXITCODE -ne 0) {
            throw 'Backend dependency install failed - the pip output is in logs\run.log. Use Python 3.12 (python.org) or install the Visual C++ Build Tools, then run this again.'
        }
        Set-Content -LiteralPath $ReqHashFile -Value $ReqHash -Encoding ASCII
    } else {
        Write-Host 'Backend dependencies are up to date.'
    }

    # -- Frontend dependencies -----------------------------------------------------------
    if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
        Write-Host 'Installing Node.js packages (first run only)...'
        Push-Location $FrontendDir
        try { & $NpmExe install --no-audit --no-fund } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed for the frontend - see logs\run.log.' }
    }

    # -- Clear stale build caches when the frontend dependencies change -------------------
    $NpmHashFile = Join-Path $FrontendDir 'node_modules\.npm_hash'
    $parts = @()
    foreach ($f in @('package.json', 'package-lock.json')) {
        $path = Join-Path $FrontendDir $f
        if (Test-Path $path) { $parts += (Get-FileHash -LiteralPath $path -Algorithm MD5).Hash }
    }
    $NpmHash       = ($parts -join '')
    $StoredNpmHash = if (Test-Path $NpmHashFile) { (Get-Content -LiteralPath $NpmHashFile -Raw).Trim() } else { '' }
    if ($NpmHash -ne $StoredNpmHash) {
        $CacheDir = Join-Path $FrontendDir 'node_modules\.cache'
        $BuildDir = Join-Path $FrontendDir 'build'
        if ((Test-Path $CacheDir) -or (Test-Path $BuildDir)) {
            Write-Host 'Clearing build caches (dependencies changed)...'
            Remove-Item -LiteralPath $CacheDir -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        Set-Content -LiteralPath $NpmHashFile -Value $NpmHash -Encoding ASCII
    }

    # -- Free ports 3000 + 8000 (stale frontend / backend) ---------------------------
    Free-Port 3000
    Free-Port 8000

    # -- Backend (dev, auto-reloads on backend\ edits); output to logs\backend*.log ---
    Write-Host 'Starting backend (dev, auto-reloads on backend\ edits)...'
    $env:PYTHONUNBUFFERED = '1'
    $script:Backend = Start-Process -FilePath $PythonExe `
        -ArgumentList @('-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload', '--reload-dir', 'backend') `
        -WorkingDirectory $Root -PassThru -NoNewWindow `
        -RedirectStandardOutput $BackendLog -RedirectStandardError $BackendErr

    # Wait for the health endpoint (60 s). Stop early if the backend process has died.
    Write-Host 'Waiting for the backend to be ready...'
    $deadline = (Get-Date).AddSeconds(60)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        if ($script:Backend.HasExited) { break }
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) {
        $tail = if (Test-Path $BackendErr) { (Get-Content -LiteralPath $BackendErr -Tail 5) -join ' | ' } else { '' }
        throw "The backend did not become ready (exit state: $(if ($script:Backend.HasExited) { "exited with code $($script:Backend.ExitCode)" } else { 'still starting after 60 s' })). Last backend errors: $tail. Full backend log: $BackendErr"
    }
    Write-Host 'Backend ready.'

    # -- Plugin servers (after the backend is up, like run.command) -----------------------
    $script:Plugins = Start-PluginServers

    Write-Host 'Launching the frontend - the app opens on a startup screen that shows the backend progress until the schema is built.'
    Push-Location $FrontendDir
    try {
        & $NpmExe run start:frontend
    } finally {
        Pop-Location
    }
}

try {
    Main
} catch {
    $exitCode = 1
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Full launcher log: $LogFile"
} finally {
    Write-Host 'Shutting down the backend and plugin servers...'
    if ($script:Backend -and -not $script:Backend.HasExited) { Stop-Process -Id $script:Backend.Id -Force -ErrorAction SilentlyContinue }
    foreach ($p in $script:Plugins) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host ''
    Write-Host "Ragnarok has stopped (exit code $exitCode). Log: $LogFile"
    try { Stop-Transcript | Out-Null } catch { }
}
exit $exitCode
