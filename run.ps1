# Ragnarok - Windows launcher (PowerShell)
# Called by run.bat with -ExecutionPolicy Bypass.
# You can also right-click this file and choose "Run with PowerShell".

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$VenvDir     = Join-Path $PSScriptRoot '.venv-pypsa'
$ReqHashFile = Join-Path $VenvDir '.req_hash'
# Frontend lives in its own package (pluggable frontend seam). The npm project
# root - package.json, public\, src\, node_modules\ - is here, not the repo root.
$FrontendDir = Join-Path $PSScriptRoot 'frontend\Ragnarok_default'
$PythonExe   = Join-Path $VenvDir 'Scripts\python.exe'
$PipExe      = Join-Path $VenvDir 'Scripts\pip.exe'

# -- Helpers -------------------------------------------------------------------

function Die([string]$msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function NeedCmd([string]$cmd, [string]$hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Die "$cmd not found. $hint"
    }
}

# -- Dependency checks ---------------------------------------------------------

NeedCmd 'git' 'Install Git from https://git-scm.com (required for the PyPSA dependency)'
NeedCmd 'npm' 'Install Node.js (includes npm) from https://nodejs.org'

# Find Python 3.11+
$Python = $null
foreach ($candidate in @('python', 'py', 'python3')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        $ok = & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $Python = $candidate; break }
    }
}
if (-not $Python) {
    Die 'Python 3.11 or later is required. Download from https://www.python.org/downloads/'
}

# -- Virtual environment -------------------------------------------------------

$RebuildVenv = $false
if (Test-Path $PythonExe) {
    $ok = & $PythonExe -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
    if ($LASTEXITCODE -ne 0) { $RebuildVenv = $true }
}

if ($RebuildVenv) {
    Write-Host 'Rebuilding virtual environment (Python version changed)...'
    Remove-Item -Recurse -Force $VenvDir
}

if (-not (Test-Path $PythonExe)) {
    Write-Host 'Creating Python virtual environment...'
    & $Python -m venv $VenvDir
}

# -- Backend dependencies (skipped when requirements.txt is unchanged) ---------

$env:MPLCONFIGDIR = Join-Path $PSScriptRoot '.matplotlib'
New-Item -ItemType Directory -Force -Path $env:MPLCONFIGDIR | Out-Null

$ReqFile    = Join-Path $PSScriptRoot 'backend\requirements.txt'
$ReqHash    = (Get-FileHash $ReqFile -Algorithm MD5).Hash
$StoredHash = if (Test-Path $ReqHashFile) { Get-Content $ReqHashFile -Raw } else { '' }

if ($ReqHash.Trim() -ne $StoredHash.Trim()) {
    Write-Host 'Installing backend dependencies...'
    & $PipExe install --upgrade pip --quiet
    & $PipExe install -r $ReqFile
    Set-Content -Path $ReqHashFile -Value $ReqHash
} else {
    Write-Host 'Backend dependencies are up to date.'
}

# -- Frontend dependencies -----------------------------------------------------

if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
    Write-Host 'Installing Node.js packages...'
    Push-Location $FrontendDir
    try { npm install } finally { Pop-Location }
}

# -- Clear stale build caches when dependencies change ------------------------
# CRA's webpack cache survives across `npm start` invocations. A dependency
# upgrade can leave cached transformed sources stale, but the everyday "just
# launch the app" case doesn't need a wipe - and an unconditional wipe forces
# a cold compile of the whole bundle on every launch (slow). Hash package.json
# + package-lock.json (mirrors the ReqHash pattern above) and only wipe when
# they actually change.

$NpmHashFile = Join-Path $FrontendDir 'node_modules\.npm_hash'
$PkgFile     = Join-Path $FrontendDir 'package.json'
$LockFile    = Join-Path $FrontendDir 'package-lock.json'
$NpmHashParts = @()
if (Test-Path $PkgFile)  { $NpmHashParts += (Get-FileHash $PkgFile  -Algorithm MD5).Hash }
if (Test-Path $LockFile) { $NpmHashParts += (Get-FileHash $LockFile -Algorithm MD5).Hash }
$NpmHash       = ($NpmHashParts -join '')
$StoredNpmHash = if (Test-Path $NpmHashFile) { (Get-Content $NpmHashFile -Raw).Trim() } else { '' }

if ($NpmHash.Trim() -ne $StoredNpmHash) {
    $CacheDir = Join-Path $FrontendDir 'node_modules\.cache'
    $BuildDir = Join-Path $FrontendDir 'build'
    if ((Test-Path $CacheDir) -or (Test-Path $BuildDir)) {
        Write-Host 'Clearing build caches (dependencies changed)...'
        if (Test-Path $CacheDir) { Remove-Item -Recurse -Force $CacheDir -ErrorAction SilentlyContinue }
        if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue }
    }
    Set-Content -Path $NpmHashFile -Value $NpmHash
} else {
    Write-Host 'Frontend build cache is up to date.'
}

# -- Free ports 3000 + 8000 (kill stale frontend / backend) --------------------

function Free-Port([int]$port) {
    $pids = @()
    try {
        $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique
    } catch { }
    foreach ($p in $pids) {
        if ($p -and $p -ne 0) {
            Write-Host "Port $port busy - killing PID $p"
            try { Stop-Process -Id $p -Force -ErrorAction Stop } catch { }
        }
    }
}

Free-Port 3000
Free-Port 8000

# -- Plugin servers (from plugins.env) -----------------------------------------
# Each non-comment line is "<server dir>|<run command>". The server can live
# anywhere on disk (e.g. another repo); plugins never talk to the Ragnarok
# backend - this just starts the local servers the frontend plugins connect to.
# Mirrors run.command's plugin launch for Windows.
function Start-PluginServers {
    $envFile = if ($env:RAGNAROK_PLUGINS_ENV) { $env:RAGNAROK_PLUGINS_ENV } else { Join-Path $PSScriptRoot 'plugins.env' }
    $procs = @()
    if (-not (Test-Path $envFile)) { return $procs }
    foreach ($line in Get-Content $envFile) {
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
        # Free this plugin's port first so a stale server can't hold it. Parse
        # the port from the run command (--port N / -p N / a trailing :N).
        $pport = $null
        if ($pcmd -match '(?:--port|-p)[\s=]+(\d+)') { $pport = [int]$Matches[1] }
        elseif ($pcmd -match ':(\d{2,5})\b') { $pport = [int]$Matches[1] }
        if ($pport) { Free-Port $pport }

        # Run in the plugin's OWN environment: if the dir ships a .venv use its
        # python (plugin deps win); otherwise fall back to the Ragnarok venv.
        $parts = $pcmd -split '\s+'
        $exe = $parts[0]
        $rest = if ($parts.Count -gt 1) { $parts[1..($parts.Count - 1)] } else { @() }
        if ($exe -ieq 'python' -or $exe -ieq 'python3') {
            $pluginPy = Join-Path $pdir '.venv\Scripts\python.exe'
            $exe = if (Test-Path $pluginPy) { $pluginPy } else { $PythonExe }
        }
        Write-Host "Starting plugin server: $pdir -> $pcmd"
        try {
            if ($rest.Count -gt 0) {
                $p = Start-Process -FilePath $exe -ArgumentList $rest -WorkingDirectory $pdir -PassThru -NoNewWindow -ErrorAction Stop
            } else {
                $p = Start-Process -FilePath $exe -WorkingDirectory $pdir -PassThru -NoNewWindow -ErrorAction Stop
            }
            $procs += $p
        } catch {
            Write-Host "Failed to start plugin server: $pdir ($($_.Exception.Message))"
        }
    }
    return $procs
}

# -- Launch --------------------------------------------------------------------

# Dev-mode launcher: enable uvicorn --reload so backend Python edits are
# picked up without manually restarting run.ps1. Scoped to --reload-dir
# backend so watchfiles ignores the venv, node_modules, and the frontend
# build cache. Caveat: if backend Python is edited while a solve is in
# flight, uvicorn restart will kill the child mp.Process worker - that is
# acceptable for dev because the solve was about to be invalidated anyway.
Write-Host 'Starting backend (dev, auto-reloads on backend/* edits)...'
$Backend = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload', '--reload-dir', 'backend' `
    -WorkingDirectory $PSScriptRoot `
    -PassThru `
    -NoNewWindow

# Wait for health endpoint (60 s timeout)
Write-Host 'Waiting for backend to be ready...'
$deadline = (Get-Date).AddSeconds(60)
$ready = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}

if (-not $ready) {
    $Backend | Stop-Process -Force -ErrorAction SilentlyContinue
    Die 'Backend did not start within 60 seconds. Check the error output above.'
}

Write-Host 'Backend ready.'

# Start any registered plugin servers (after the backend is up, like run.command).
$Plugins = Start-PluginServers

Write-Host 'Launching frontend - the app opens on a startup screen that shows'
Write-Host 'the backend progress until the schema is built.'

Push-Location $FrontendDir
try {
    npm run start:frontend
} finally {
    Pop-Location
    Write-Host 'Shutting down backend and plugin servers...'
    $Backend | Stop-Process -Force -ErrorAction SilentlyContinue
    foreach ($p in $Plugins) {
        if ($p) { try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { } }
    }
}
