# Ragnarok — Windows launcher (PowerShell)
# Called by run.bat with -ExecutionPolicy Bypass.
# You can also right-click this file and choose "Run with PowerShell".

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$VenvDir     = Join-Path $PSScriptRoot '.venv-pypsa'
$ReqHashFile = Join-Path $VenvDir '.req_hash'
$PythonExe   = Join-Path $VenvDir 'Scripts\python.exe'
$PipExe      = Join-Path $VenvDir 'Scripts\pip.exe'

# ── Helpers ───────────────────────────────────────────────────────────────────

function Die([string]$msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function NeedCmd([string]$cmd, [string]$hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Die "$cmd not found. $hint"
    }
}

# ── Dependency checks ─────────────────────────────────────────────────────────

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

# ── Virtual environment ───────────────────────────────────────────────────────

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

# ── Backend dependencies (skipped when requirements.txt is unchanged) ─────────

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

# ── Frontend dependencies ─────────────────────────────────────────────────────

if (-not (Test-Path (Join-Path $PSScriptRoot 'node_modules'))) {
    Write-Host 'Installing Node.js packages...'
    npm install
}

# ── Clear stale build caches ──────────────────────────────────────────────────
# The CRA webpack cache survives across `npm start` invocations and has caused
# users to keep seeing pre-fix bundles after a code change. Always wipe it on
# launch so the dev server compiles a fresh bundle.

$CacheDir = Join-Path $PSScriptRoot 'node_modules\.cache'
$BuildDir = Join-Path $PSScriptRoot 'build'
if ((Test-Path $CacheDir) -or (Test-Path $BuildDir)) {
    Write-Host 'Clearing build caches (node_modules\.cache, build\)...'
    if (Test-Path $CacheDir) { Remove-Item -Recurse -Force $CacheDir -ErrorAction SilentlyContinue }
    if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue }
}

# ── Free ports 3000 + 8000 (kill stale frontend / backend) ────────────────────

function Free-Port([int]$port) {
    $pids = @()
    try {
        $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique
    } catch { }
    foreach ($p in $pids) {
        if ($p -and $p -ne 0) {
            Write-Host "Port $port busy — killing PID $p"
            try { Stop-Process -Id $p -Force -ErrorAction Stop } catch { }
        }
    }
}

Free-Port 3000
Free-Port 8000

# ── Launch ────────────────────────────────────────────────────────────────────

Write-Host 'Starting backend...'
$Backend = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000' `
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

Write-Host 'Backend ready. Opening app in browser...'

try {
    npm run start:frontend
} finally {
    Write-Host 'Shutting down backend...'
    $Backend | Stop-Process -Force -ErrorAction SilentlyContinue
}
