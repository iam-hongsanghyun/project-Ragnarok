# Ragnarok - run the app as ONE process (API + web UI on a single port). Windows.
#
# Usage:  .\serve.ps1 [local|server]
#   local  (default) -> binds 127.0.0.1 : only this machine
#   server           -> binds 0.0.0.0   : any machine on your LAN (see warning)
#
# Deployment / "just use it" launcher (contrast run.* = DEV mode). One uvicorn
# worker serves the committed web build at .\build together with the API; no
# --reload, single worker (SQLite stores are single-writer). PowerShell 5.1 OK.
param([ValidateSet('local','server')][string]$Mode = 'local')

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$BindHost  = if ($Mode -eq 'server') { '0.0.0.0' } else { '127.0.0.1' }
$Frontend  = Join-Path $PSScriptRoot 'frontend\Ragnarok_default'
$VenvDir   = Join-Path $PSScriptRoot '.venv-pypsa'
$PythonExe = Join-Path $VenvDir 'Scripts\python.exe'
$PipExe    = Join-Path $VenvDir 'Scripts\pip.exe'
$Port      = if ($env:RAGNAROK_PORT) { $env:RAGNAROK_PORT } else { '8000' }

function Die([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

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

# Verify the venv actually imports the core deps (a matching hash isn't enough:
# a prior install may have failed, or the venv was copied in). PowerShell does
# not throw on native non-zero exits, so check $LASTEXITCODE and only stamp the
# hash on success.
& $PythonExe -c "import uvicorn, fastapi" 2>$null
$DepsOk = ($LASTEXITCODE -eq 0)
if ($ReqHash.Trim() -ne $StoredHash -or -not $DepsOk) {
    Write-Host 'Installing backend dependencies...'
    & $PipExe install --upgrade pip --quiet
    & $PipExe install -r $ReqFile
    if ($LASTEXITCODE -ne 0) { Die 'Backend dependency install failed - see the pip error above. Fix it (e.g. use Python 3.11/3.12, or install build tools) and re-run.' }
    Set-Content -Path $ReqHashFile -Value $ReqHash
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

# -- Announce URL(s) -------------------------------------------------------------
Write-Host ''
if ($Mode -eq 'server') {
    Write-Host 'Server mode - open from any machine on this network:'
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }
    foreach ($ip in $ips) { Write-Host "  http://$($ip.IPAddress):$Port" }
    Write-Host "  http://$($env:COMPUTERNAME).local:$Port"
    Write-Host ''
    Write-Host 'WARNING: no authentication - trusted networks only (plugin install runs'
    Write-Host 'uploaded Python by design). Do not expose to the internet.'
} else {
    Write-Host 'Local mode - open on this machine:'
    Write-Host "  http://127.0.0.1:$Port"
}
Write-Host ''

& $PythonExe -m uvicorn backend.app.main:app --host $BindHost --port $Port
